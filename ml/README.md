# ML: the TriageModel pipeline

The customer side priority comes from the distilled TriageModel (`triage/`, copied from
`../TriageModel`): a MiniLM embedding plus 18 engineered signals into a small multi task head.
The triage service runs its exported numpy weights (`services/triage/models/`), so it carries no torch.

| Piece | Role |
|---|---|
| `triage/` | Schema, labelling, corpus and trainer (`triage/train/train_triage.py`) |
| `dvc.yaml`, `params.yaml` | Pipeline: `train` then `export` then `evaluate` |
| `export_triage.py` | `.pt` to `triage_multitask.npz` and `.json` |
| `evaluate.py` | Candidate metrics for the promotion gate (`metrics/candidate.json`) |
| `dags/retrain_triage.py` | Airflow: version data, `dvc repro`, gate against MLflow, promote, reload |
| `models-live/` | Promoted weights, mounted read only into triage at `/models-live` |

## Run it

```bash
docker compose --profile mlops up -d      # MLflow http://localhost:5000, Airflow http://localhost:8081
docker compose logs airflow | grep -i password    # the standalone admin password
```

Trigger `retrain_triage` in Airflow, or by hand:

```bash
pip install dvc mlflow torch sentence-transformers scikit-learn pyyaml
cd ml && dvc repro && cat metrics/candidate.json
```

Data under `triage/data` is not in git: the DAG's first task runs `dvc add ml/triage/data`,
which writes `ml/triage/data.dvc`. Add a remote (`dvc remote add -d store s3://...`) and
`dvc push` to share it. A candidate is promoted only when its macro F1 beats the MLflow run
tagged `production` by `gate.min_improvement` and it stays under `gate.max_latency_ms`.
