"""Configuration testing: every compose combination the project ships must be valid.

No containers are started here, so this one runs anywhere Docker is installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMBOS = [
    ["compose.yaml"],
    ["compose.yaml", "compose.lite.yaml"],
    ["compose.yaml", "compose.ci.yaml"],
    ["compose.yaml", "compose.gpu.yaml"],
    ["compose.yaml", "compose.prod.yaml"],
    ["compose.yaml", "compose.test.yaml"],
    ["compose.yaml", "compose.ci.yaml", "compose.test.yaml"],
    ["compose.yaml", "compose.prod.yaml", "compose.monitoring.yaml"],
]

#: compose.prod.yaml refuses to render without a host name, which is the point of it.
ENV = {"SITE_DOMAIN": "lankalink.example.lk", "GRAFANA_ADMIN_PASSWORD": "configuration-test"}


@pytest.mark.skipif(not shutil.which("docker"), reason="docker is not installed")
@pytest.mark.parametrize("files", COMBOS, ids=lambda f: "+".join(x.replace("compose.", "").replace(".yaml", "") for x in f))
def test_the_compose_file_is_valid(files):
    args = ["docker", "compose"]
    for f in files:
        args += ["-f", f]
    import os
    r = subprocess.run([*args, "config", "-q"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, **ENV})
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not shutil.which("docker"), reason="docker is not installed")
def test_the_mlops_profile_adds_airflow_and_mlflow():
    r = subprocess.run(["docker", "compose", "--profile", "mlops", "config", "--services"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert {"mlflow", "airflow"} <= set(r.stdout.split())


def test_every_variable_the_compose_file_reads_is_in_the_example():
    """A missing key in .env.example is a deployment that starts and then fails at runtime."""
    import re
    example = {m.group(1) for m in re.finditer(r"(?m)^([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(encoding="utf-8"))}
    used = set()
    example |= {"SITE_DOMAIN", "ACME_EMAIL", "PUBLIC_PROBE_URL"}  # written by the deploy, or an optional override
    for f in ("compose.yaml", "compose.ci.yaml", "compose.gpu.yaml", "compose.lite.yaml", "compose.prod.yaml",
              "compose.test.yaml", "compose.monitoring.yaml"):
        text = (ROOT / f).read_text(encoding="utf-8")
        used |= {m.group(1) for m in re.finditer(r"\$\{([A-Z][A-Z0-9_]*)[:\-}]", text)}
    assert not (used - example), f"not in .env.example: {sorted(used - example)}"
