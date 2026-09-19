# Lanka Link v3: Test Evaluation Summary

Run of 19 Sep 2026, against the plan in `docs/TEST-PLAN.md`.

**Where it ran.** The full compose stack on the development laptop (Windows 11, Docker Desktop),
all sixteen services plus both models resident, database on Neon in **us-east-2 (Ohio)**, about
320 ms per round trip from the laptop. The drafting model was `gpt-oss:120b-cloud` through Ollama,
with Gemini as the fallback binding. These are development-machine figures, not a server
benchmark.

## 1. Summary

| Technique | Suite | Result |
| --- | --- | --- |
| Unit and contract | `scripts/test-all.sh` | **Pass.** 128 tests, 2 Node tests, 6 module self-checks, lint and types clean |
| Data and database integrity | `tests/system/test_data_integrity.py` | **Pass.** 8 of 8 |
| Function | `tests/system/test_functional.py` | **Pass.** 6 of 6 |
| Security and access control | `tests/system/test_access_control.py` | **Pass.** 15 of 15 |
| Performance profiling | `tests/system/test_performance.py` | **Pass.** 8 of 8 |
| Configuration | `tests/system/test_configuration.py` | **Pass.** 7 of 7 |
| Failover and recovery | `tests/system/test_resilience.py` | **Pass.** 4 of 4 after fixing D5 and D9 (3 of 4 on the first run) |
| User interface | `web/e2e` (Playwright, Chromium) | **Pass.** 11 of 11 |
| Scenario: headline case | `scripts/demo_flow.py` | **Pass.** Cites payment and outage; Sinhala reply delivered |
| Scenario: hot model swap | `scripts/verify_hot_swap.py` | **Pass** |
| Load | `scripts/load.sh` (k6) | **Zero errors, latency thresholds failed.** See section 3; the cause is the database region |

The final run of the whole system suite, with the destructive resilience tests switched on
(`LANKA_RESILIENCE=1`): **48 passed, 0 skipped, 0 failed**, in 3 min 17 s.

Nine defects were found and all nine were fixed in this iteration. Separately, the load latency
thresholds still fail; that needs the database move, not a code fix.

## 2. What was proven

**It tells the truth.** The headline case ran end to end with a real model: Ravi (suspended, and
inside a seeded outage) wrote in Sinhala, and the draft cited both the unpaid balance of
LKR 8,450.00 and the line fault. The Sinhala reply that reached him carried the amount unchanged
(රුපියල් 8,450.00). The function suite checks the same thing mechanically on every run: the
digits in the English draft and in the translated reply must match, step numbers aside.

**The wrong person does not see the wrong data.** No token: 401 on every route tried. A customer
token on the console, admin and lab surfaces: 403. An agent token on admin and lab: 403. Each role
on its own surface: 200. Two customers fetching each other's ticket: 404, never the row. A token
with a tampered signature: 401. A wrong password: refused.

**It stays up when a part does not.** With audio stopped the message is still accepted. With
grounding stopped the model map reports it down rather than healthy. A restarted translation
service rejoins with no other action. With translation stopped the case still opens and still
reaches a draft (after the fix for D5).

**It is fast enough on a warm path.** Medians on a warm connection, single user:

| Route | Median | Budget |
| --- | --- | --- |
| `/api/app/billing`, `/api/app/plan`, `/api/app/notices` | 5 to 6 ms (cached) | 800 ms |
| `/api/me` | 6 ms warm, 573 ms cold | 800 ms |
| `/api/app/overview` | 6 ms warm, about 3.1 s cold | 1500 ms warm |
| `/api/app/usage` | about 600 ms | 1200 ms |
| Message acknowledgement | about 1.1 s | 2500 ms |
| Console queue (needs approval) | about 2.6 s cold | 3000 ms |
| Any page shell | 13 to 19 ms | none set |

## 3. Load

k6, 5 inquiries a second for one minute, up to 20 virtual users:

| Metric | Result | Threshold | Verdict |
| --- | --- | --- | --- |
| Requests | 602, **0 failed** | under 1 percent failed | Pass |
| Checks | 601 of 601 | | Pass |
| Acknowledgement p50 | 1.14 s | 300 ms | **Fail** |
| Acknowledgement p95 | 2.4 s | 800 ms | **Fail** |
| Overview p50 | 4.8 ms | 250 ms | Pass |

The system held the rate with no errors. The acknowledgement is a gateway call plus an inquiry
write, which is three sequential Neon round trips, and each one costs about 320 ms from here to
Ohio. That is the whole of the 1.1 s median. The same three round trips to Singapore are about
35 ms each, which puts the median near 150 ms, inside the threshold. The fix is the region move
(`scripts/neon-move.sh`), not code, and this threshold is recorded as failing until that is done.

## 4. Defects found

| # | Found by | Defect | Cause | Fix |
| --- | --- | --- | --- | --- |
| D1 | Configuration | `LANKA_LLM_IMPL` and `LANKA_TR_BACKEND` are read by compose but missing from `.env.example` | Added to compose without updating the example | Both added to `.env.example` with their defaults |
| D2 | Function (scenario) | A Sinhala reply ran two words together: "නමුත්‍රේඛා" for "නමුත් රේඛා" (but the line) | The conjunct repair joined any virama followed by ර or ය, including across a real word boundary | The repair now joins across a space only when the piece before is a bare consonant or an anusvara, or when what follows is a bare ර or ය; unit tests for both directions |
| D3 | Function (scenario) | "සාමාන් ය" left broken after the D2 fix | The tighter rule refused a genuine break after a vowel sign | A lone ර or ය is never a word, so it is joined; unit test added |
| D4 | User interface | The chat test opened `/app/support`, which no longer exists, and waited for a test id that nothing renders | Support moved to tickets; the test was never updated | Test rewritten against the real flow: open a ticket, land on it, see it waiting |
| D5 | Failover and recovery | A newly opened case can be missing from the console's "All" tab | The list is ordered oldest first and capped at 100 rows, so once there are more than 100 cases the newest ones fall off the end | "All" is now newest first. The work queues ("Needs approval", "Open") stay oldest first, since the customer who has waited longest is served first |
| D6 | Load | `scripts/load.sh` fails on Windows before k6 runs | Git Bash rewrites `/load` in the Docker volume argument into a Windows path | `MSYS_NO_PATHCONV=1` on the docker call |
| D7 | System (all) | Test sessions fail with 429 when several open at once | Better Auth rate limits sign-in per address | The HTTP helper and the Playwright helper back off and retry |
| D8 | User interface | The immersion test never finished | It waited for `networkidle`, which never arrives because the live updates stream stays open | Waits for content instead |
| D9 | Failover and recovery | The translation outage test reported "no draft" although the product had written one (case LL-10946: translate failed after 3 s, the pipeline carried on, draft in 5.6 s) | The test took whichever case changed first, which could be another persona's case or a revision bump | The function and failover tests now find their case by the text of the message they sent |

D4, D6, D7, D8 and D9 were defects in the tests or the tooling, not in the product. They are listed
because a suite that fails for its own reasons hides the product's failures.

Also changed in this iteration, on request rather than as a defect: the em dash gate was removed
from GitHub Actions and from `scripts/test-all.sh`. The runtime check that holds back a reply
containing an em dash is unchanged.

## 5. Gaps

- **Speech in Sinhala and Tamil is not proven.** Every voice note run used English audio (about
  5 s to transcribe inside the pipeline). A Sinhala clip is needed to close this.
- **The load thresholds** stay red until the database is in Singapore (section 3).
- **Chromium only.** Firefox and Safari were not run.
- **Visual appearance** is not automated and was not reviewed in this run.
- **Drafts can carry markdown emphasis.** One Sinhala reply in this run contained `8,450.00**`, left
  over from bold markup in the model's English. Not a correctness defect (the amount is right), but
  it is visible to the customer; stripping markdown before translation is the fix.
- **The MLOps profile** (Airflow, MLflow) was not part of this run.

## 6. How to repeat this run

```bash
bash scripts/test-all.sh                                        # no stack needed
bash scripts/up.sh                                              # or up.ps1 on Windows
uv run --with httpx python -m pytest tests/system -q
LANKA_RESILIENCE=1 uv run --with httpx python -m pytest tests/system/test_resilience.py -q
(cd web && npx playwright install chromium && npx playwright test)
uv run --with httpx python scripts/demo_flow.py --strict
uv run --with httpx python scripts/verify_hot_swap.py
bash scripts/load.sh
```
