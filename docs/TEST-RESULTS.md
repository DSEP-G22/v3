# Lanka Link v3: Test Evaluation Summary

Run of 20 Sep 2026, against the plan in `docs/TEST-PLAN.md`. The written report built from this
run, with screenshots, is `docs/test-report/`.

**Where it ran.** `bash scripts/test-plan.sh` on the development laptop (Windows 11, Docker
Desktop, 16 cores, 7.9 GB given to Docker): the full stack, all sixteen services with both models
resident, on the **isolated test database** (`compose.test.yaml`), built from nothing by the same
migration and seed production uses. Drafting and diagnosis ran on Ollama Cloud `gpt-oss:120b` and
`20b`, triage on Groq `qwen/qwen3.8-27b`, translation on NLLB-200. The previous run (19 Sep) used
the shared Neon database; nothing that writes does that any more.

## 1. Summary

| Step | Executed | Result | Time |
| --- | --- | --- | --- |
| Unit and contract (`scripts/test-all.sh`) | 131 tests, 2 Node tests, 6 self-checks, lint, types | **Pass** | 18 s |
| Stack up and smoke (from an empty database) | 25 containers | **Pass** | 59 s |
| System (`tests/system`, resilience on) | 51 tests | **Pass** | 102 s |
| Browser (`web/e2e`, desktop and mobile) | 16 tests, 26 pages on a phone | **Pass** | 90 s |
| Scenario: headline case (`demo_flow.py --strict`) | 1 | **Pass** | 32 s |
| Scenario: hot model swap (`verify_hot_swap.py`) | 1 | **Pass** | 1 s |
| Load, write path (`load/ack.js`) | 300 tickets in 60 s, 602 requests | **Pass**, every threshold met | 62 s |

**199 test cases, 0 failed, 0 skipped.** Evidence (logs, JUnit XML, k6 summaries, screenshots of
every phone page and of each terminal step) is in `reports/2026-09-20-final/`, and the same run
can be produced by anyone with `bash scripts/test-plan.sh` or the `test-plan` GitHub workflow.

## 2. What was proven

**It tells the truth.** Ravi (suspended, inside a seeded outage) wrote in Sinhala. The draft cited
both the unpaid balance and the fibre break, and the Sinhala reply carried the amount unchanged.
The function suite checks the same mechanically: the digits in the English draft must equal the
digits in the translated reply.

**The wrong person does not see the wrong data.** 15 access control tests: no token 401, customer
token on staff routes 403, agent token on admin routes 403, each role on its own surface 200, a
tampered token 401, a wrong password refused. Two customers cannot read each other's tickets; on a
fresh database that test now opens the tickets it needs instead of skipping.

**It stays up when a part does not.** With translation stopped the case still opens and still
reaches a draft; with audio stopped the message is still accepted; with grounding stopped the map
reports it down; a restarted service rejoins by itself. New: when the Groq triage model is slow,
failing or rate limited, the distilled TriageModel scores the case and the reasons say so.

**It works on a phone.** Every page of all four surfaces at 375 px: no page scrolls sideways, the
customer app has a bottom tab bar, the agent inbox is a card list and the model map is a list.

**It is fast on the paths people wait for.** Acknowledgement p50 9.7 ms and p95 14 ms under 5 new
tickets a second (budgets 300 and 800 ms); account overview p50 4.8 ms (budget 250 ms); 0 failed
requests out of 602. These are against the local test database, so they measure the code, not the
network; production figures are in the report.

## 3. Load and capacity

k6, 5 new tickets a second for one minute, 20 virtual users, every ticket running the full
pipeline:

| Metric | Result | Threshold | Verdict |
| --- | --- | --- | --- |
| Requests | 602, 0 failed | under 1 percent | Pass |
| Tickets opened | 300 in 60 s | | |
| Acknowledgement p50 / p95 | 9.7 ms / 14.0 ms | 300 ms / 800 ms | Pass |
| Overview p50 | 4.8 ms | 250 ms | Pass |

Behind the acknowledgement, all 312 cases of the run were created and triaged. Triage used Groq
for 45 of them (315 ms average) and its own model for 267, because Groq's free tier allows 8,000
tokens a minute; no triage failed. The stages that call an external language model are where
capacity ends: 290 diagnoses reached the 15 s budget and 285 drafts the 60 s budget, so those
cases reached an agent without a proposed reply. Drafts that completed took 16.8 s at the median.
The system fails safe (no message lost, no error shown), and about fifteen drafts a minute is the
ceiling with the current model account.

## 4. Defects found and fixed in this iteration

| # | Found by | Defect | Fix |
| --- | --- | --- | --- |
| D10 | Clean install | inquiry never starts on an empty database: a backfill read `inquiry.message` before the statement that creates it | Backfill moved after the table |
| D11 | Clean install | The seed forced TLS on every database connection | TLS only when the connection string asks for it |
| D12 | Browser | Signing out of the customer area landed on sign-in, not the website | One `signOutTo` helper; the role gate holds while leaving |
| D13 | Reading the Sinhala reply | A conjunct split by a space ("මධ් යම") | **Open**: needs a word list to tell a split conjunct from a word boundary |
| D14 | Groq triage | Every second call returned 429 | `max_tokens` and `temperature` per binding; Groq reserved its whole per-minute budget otherwise |
| D15 | Browser (mobile) | `/plans` was empty after every deploy until the cache expired | Rendered per request with a one minute data cache |
| D16 | Browser (mobile) | Four pages scrolled sideways; the customer menu hid four of six items | Bottom tab bar, card lists, and the overflow causes |
| D17 | System (functional) | A new case could fall past the console's 100 row cap after a burst | The All tab is ordered by time alone (D5 was only half fixed) |
| D18 | System (functional) | Drafts slower than 30 s were lost although drafting is allowed 60 s | Each stage call now times out at its own budget |
| D19 | Scenario | A reply quoting an incident id (`INC-2026-0418`) or an ISO date was held as "a phone number" | A phone is ten or more digits standing alone |
| D20 | Scenario | Markdown reached the customer (`**LKR 18,574.40**`) | `plain_text()` strips markdown after the stream is joined |
| D21 | Test stack | `migrate` failed on a fresh volume | Postgres health checks go over TCP, not the socket the init server uses |
| D22 | Production monitoring | cAdvisor saw no containers | v0.55.1: older builds cannot read Docker 29's containerd image store |

D19 also proved the compliance guard works: the same draft was correctly held for promising an
outage credit the customer is not entitled to.

## 5. Gaps

- **Speech is proven in English only.** No Sinhala or Tamil voice sample has been run.
- **Sinhala conjunct repair (D13)** is open.
- **Chromium only**, on desktop and a 375 px phone profile.
- **The write-path load test runs on a development machine.** Production is load tested read only.
- **External model capacity** is the pipeline's ceiling (section 3), not yet addressed.
- **The seeded demo passwords are public** and still work on the public site.
- **The MLOps profile** (Airflow, MLflow) was not part of this run.

## 6. How to repeat this run

```bash
bash scripts/test-plan.sh                       # everything, on a throwaway database
STEPS="system browser" bash scripts/test-plan.sh  # one part of it
SCRIPT=load/browse.js LANKA_URL=https://<domain> bash scripts/load.sh   # read only, safe on production
```

Or run the **test-plan** workflow from the Actions tab and download its artifact. The report is
rebuilt from a run with `python docs/test-report/build_report.py --collect reports/<date>` and
`powershell -File docs/test-report/export.ps1 docs/test-report/Lanka-Link-v3-Master-Test-Plan.docx`.
