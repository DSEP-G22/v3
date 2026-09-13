"""Weekly TriageModel retrain: version data, DVC pipeline, MLflow gate, promote, hot reload.

    docker compose --profile mlops up -d        Airflow on :8081, MLflow on :5000

Each task shells out to the same commands a developer runs by hand (`dvc repro` in ml/), so
there is one code path. Only the last two tasks change what production serves, and only when
the candidate beat the MLflow production run on gold, inside the latency budget.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator, ShortCircuitOperator

REPO = Path(os.getenv("DSEP_REPO_ROOT", "/opt/repo"))
ML = REPO / "ml"
LIVE = ML / "models-live"
TRIAGE_URL = os.getenv("TRIAGE_URL", "http://triage:8000")
EXPERIMENT = "triage_distillation"

DEFAULT_ARGS = {"owner": "lanka-link", "retries": 1, "retry_delay": timedelta(minutes=10), "depends_on_past": False}


def _params() -> dict:
    import yaml

    return yaml.safe_load((ML / "params.yaml").read_text(encoding="utf-8"))


def gate(**context) -> bool:
    """Compare the candidate with the MLflow run tagged production. False skips promotion."""
    import mlflow

    candidate = json.loads((ML / "metrics" / "candidate.json").read_text(encoding="utf-8"))
    g = _params()["gate"]
    client = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT)
    incumbent = 0.0
    if experiment:
        runs = client.search_runs([experiment.experiment_id], filter_string="tags.production = 'true'",
                                  order_by=["start_time DESC"], max_results=1)
        if runs:
            incumbent = runs[0].data.metrics.get("f1_mean", 0.0)

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"candidate-{context['ds']}") as run:
        mlflow.log_params(_params()["train"])
        mlflow.log_metrics({k: float(v) for k, v in candidate.items() if isinstance(v, (int, float))})
        mlflow.log_artifacts(str(ML / "build" / "triage"), artifact_path="model")
        mlflow.log_artifact(str(ML / "triage" / "artifacts" / "score_table.json"))
        improved = candidate["f1_mean"] >= incumbent + g["min_improvement"]
        mlflow.set_tags({"incumbent_f1_mean": incumbent, "improved": improved,
                         "within_latency": candidate["within_latency"]})
        context["ti"].xcom_push(key="run_id", value=run.info.run_id)

    print(f"candidate {candidate['f1_mean']} vs production {incumbent}; latency ok {candidate['within_latency']}")
    return bool(improved and candidate["within_latency"])


def promote(**context) -> None:
    """Tag the run production, and copy its weights where the triage service reads them."""
    import mlflow

    client = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT)
    for old in client.search_runs([experiment.experiment_id], filter_string="tags.production = 'true'"):
        client.set_tag(old.info.run_id, "production", "false")
    client.set_tag(context["ti"].xcom_pull(task_ids="gate", key="run_id"), "production", "true")

    LIVE.mkdir(parents=True, exist_ok=True)
    staging = LIVE.with_name("models-live.new")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(ML / "build" / "triage", staging)
    for f in staging.iterdir():  # replace file by file so a reader never sees a half written model
        os.replace(f, LIVE / f.name)
    shutil.rmtree(staging, ignore_errors=True)


with DAG(
    dag_id="retrain_triage",
    description="Distil the TriageModel again from the latest labelled data and promote it if it is better",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule="@weekly",
    catchup=False,
    max_active_runs=1,
    tags=["lanka-link", "ml"],
) as dag:
    version_data = BashOperator(
        task_id="version_data",
        bash_command=f"cd {REPO} && ([ -d .dvc ] || dvc init --no-scm -q) && dvc add ml/triage/data -q",
    )
    repro = BashOperator(task_id="dvc_repro", bash_command=f"cd {ML} && dvc repro")
    check = ShortCircuitOperator(task_id="gate", python_callable=gate)
    promote_task = PythonOperator(task_id="promote", python_callable=promote)
    reload = BashOperator(task_id="reload_triage", bash_command=f"curl -fsS -X POST {TRIAGE_URL}/reload")

    version_data >> repro >> check >> promote_task >> reload
