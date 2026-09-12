# Lanka Link v3

One endpoint (`http://localhost:8080`), every service in its own image, one `docker compose up`.
Build plan: [PLAN.md](PLAN.md).

| Path | Who | What |
|---|---|---|
| `/` `/plans` | anyone | Landing and plan catalogue |
| `/app` | customers | Home, billing, usage, plan, settings, support chat (text, photo, voice) |
| `/console` | agent, lead, admin | Case inbox, drafts, approve or send back (Ctrl K finds a case) |
| `/admin` | admin | Auto reply policy, model bindings (hot swap), grounding plan, traces, users |
| `/sim` | operator, admin | Sim clock, network, scenarios and faults, customers, test lab, event log |

## Run

```bash
cp .env.example .env        # fill NEON_KEY and BETTER_AUTH_SECRET (openssl rand -base64 32)
scripts/up.sh               # or scripts\up.ps1
scripts/smoke.sh            # or scripts\smoke.ps1
uv run python scripts/neon-latency.py
```

Seeded logins (passwords from `SEED_*_PASSWORD` in `.env`):
- Staff: `agent1`, `lead1`, `admin1`, `operator1` `@lankalink.example.lk`
- Customers: `amara`, `ravi`, `nadia`, `dinesh`, `priya`, `kavindu`, `thilini`, `rizwan` `@customers.lankalink.example.lk`

Profiles:
- GPU: `docker compose -f compose.yaml -f compose.gpu.yaml up -d` (local Ollama, CUDA whisper and NLLB).
- CI: `docker compose -f compose.yaml -f compose.ci.yaml up -d --wait` (no model images, stub LLM).

## Verify

```bash
scripts/test-all.sh                                 # unit, architecture, em dash, typecheck, no mock data
uv run python scripts/verify_hot_swap.py            # rebinds llm_draft live and restores it
uv run python scripts/demo_flow.py --strict         # the headline case through :8080
scripts/e2e.sh                                      # Playwright, including the immersion scan
scripts/load.sh                                     # k6 thresholds
```

## Images

`release.yml` pushes `ghcr.io/<owner>/lanka-link-v3-<svc>` on main and `v*` tags. GHCR packages start
private: make them public in the package settings, or `docker login ghcr.io` before `docker compose pull`.
`scripts/publish-images.sh` does the same by hand. `scripts/repo-init.sh <name>` creates the GitHub repo.

## Security

`.env` holds a live Neon password and is gitignored; gitleaks runs in CI and in `repo-init.sh`.
Rotate the Neon password if it was ever shared. Payments are a stub: no card data is collected.
