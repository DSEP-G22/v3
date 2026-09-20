# Lanka Link v3

One endpoint (`http://localhost:8080`), every service in its own image, one `docker compose up`.
Build plan: [PLAN.md](PLAN.md). Full feature guide: **http://localhost:8080/docs**.

| Path | Who | What |
|---|---|---|
| `/` `/plans` `/docs` | anyone | Landing, plan catalogue, how it all works |
| `/app` | customers | Home, **tickets** (photo and voice attachments, live progress, notices, feedback), billing, usage, plan, settings |
| `/console` | agent, lead, admin | Queue with both priorities, drafts, approve or send back (Ctrl K finds a case) |
| `/admin` | admin | Overview with customer feedback, auto reply, model bindings (hot swap), grounding plan, traces, users |
| `/sim` | operator, admin | Sim clock, live network topology, incidents (network and customer), customers, test lab, event log |

## Run

```bash
cp .env.example .env        # NEON_KEY, BETTER_AUTH_SECRET (openssl rand -base64 32), optional keys
scripts/up.sh               # or scripts\up.ps1: the full stack
# Same stack, same command as before: every stage, translation and speech included (about 4 GB RAM)
docker compose -f compose.yaml -f compose.lite.yaml up -d --wait
```

Seeded logins (passwords from `SEED_*_PASSWORD` in `.env`):
- Staff: `agent1`, `lead1`, `admin1`, `operator1` `@lankalink.example.lk`
- Customers: `amara`, `ravi`, `nadia`, `dinesh`, `priya`, `kavindu`, `thilini`, `rizwan` `@customers.lankalink.example.lk`

Profiles:
- **Lite**: `-f compose.lite.yaml`, now identical to the full stack (kept so the command still works).
- **GPU**: `-f compose.gpu.yaml`, local Ollama, CUDA whisper and NLLB.
- **CI**: `-f compose.ci.yaml`, no model images and the offline stub LLM.
- **MLOps**: `--profile mlops`, MLflow on :5000 and Airflow on :8081 (see [ml/README.md](ml/README.md)).

## How a reply is decided

- **Two priorities per case.** Customer side: the distilled TriageModel (MiniLM plus 18 signals,
  numpy weights in `services/triage/models`). Our side: rules over the account and network record
  (`services/grounding/app/priority.py`). The queue sorts by the higher one.
- **Customer side first.** The draft opens with what the customer reported on their own equipment
  (steps only from device guidance and procedures), then anything on our side.
- **Triage model.** The customer side priority comes from Groq (`qwen/qwen3.8-27b` by default; gpt-oss
  20b/120b and compound are selectable) or the distilled TriageModel, which also answers whenever Groq
  is slow or rate limited.
- **LLM.** Bindings are set live in `/admin/models`. The default is Ollama `gpt-oss:120b-cloud` via the
  host daemon (`OLLAMA_BASE_URL`), with the offline stub for CI.
- **Tracing.** `LANGSMITH_TRACING=true` plus `LANGSMITH_API_KEY`: one trace per case revision, every stage
  nested, and the draft as an LLM run with its exact prompt.

## Verify

```bash
bash scripts/test-plan.sh                           # the whole test plan on a throwaway database, evidence in reports/<date>/
scripts/test-all.sh                                 # unit, architecture, em dash, typecheck, no mock data
uv run python scripts/verify_hot_swap.py            # rebinds llm_draft live and restores it
uv run python scripts/demo_flow.py --strict         # the headline case through :8080
scripts/e2e.sh                                      # Playwright, including the immersion scan
scripts/load.sh                                     # k6 thresholds
SCRIPT=load/browse.js LANKA_URL=https://... scripts/load.sh   # read-only load, safe on production
```

`compose.test.yaml` runs the stack on its own Postgres: tests and load never touch the shared Neon
database. The same plan runs in GitHub Actions (`test-plan` workflow). Plan and report:
[docs/TEST-PLAN.md](docs/TEST-PLAN.md), [docs/test-report](docs/test-report).

## Monitor

Production runs `compose.monitoring.yaml` beside the stack: Prometheus, node-exporter, cAdvisor,
blackbox probes and Grafana at `/grafana` with the provisioned dashboard **Lanka Link: VPS and
services**. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) section 7.

## Images

`release.yml` pushes `ghcr.io/<owner>/lanka-link-v3-<svc>` on main and `v*` tags. GHCR packages start
private: make them public in the package settings, or `docker login ghcr.io` before `docker compose pull`.
`scripts/publish-images.sh` does the same by hand. `scripts/repo-init.sh <name>` creates the GitHub repo.

## Security

`.env` holds a live Neon password and is gitignored, and so kept out of every image build
(`.dockerignore`); gitleaks runs in CI and in `repo-init.sh`. Rotate the Neon password if it was ever
shared. Payments are a stub: no card data is collected.
