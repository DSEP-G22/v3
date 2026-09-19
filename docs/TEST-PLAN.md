# Lanka Link v3: Master Test Plan

Version 2.0

| Date | Version | Description | Author |
| --- | --- | --- | --- |
| 19 Sep 2026 | 1.0 | First master test plan: covers the whole v3 system through its edge. | DSEP Group 22 |
| 20 Sep 2026 | 2.0 | Isolated test stack, one-command runner and workflow, mobile suite, Groq triage, production read-only load test, monitoring. | DSEP Group 22 |

---

## 1. Evaluation Mission and Test Motivation

### 1.1 Background

Lanka Link v3 is a support system for a Sri Lankan internet provider. A customer writes in
Sinhala, Tamil, Singlish, Tanglish or English, from a browser, and may attach a photo of their
router or a voice note. The system transcribes the voice note, translates the message into
English, pulls the customer's line, bill and area record, decides which department owns the
problem, retrieves the procedure that applies, writes a reply grounded only in what it can
prove, and puts that reply in front of a human agent, who approves it or sends it back. The
approved reply goes back to the customer in the language they wrote in.

It is sixteen services behind one edge, two large models on the request path (NLLB-200 for
translation, faster-whisper for speech), a language model for diagnosis and for drafting, and
three stores: Neon Postgres for the business and case record, TimescaleDB for events, MinIO for
attachments. Any of those can be slow, wrong or absent, and the product still has to answer.

### 1.2 Mission

This plan exists to answer four questions, in this order:

1. **Does it tell the truth?** A reply that quotes a balance, a wait or an appointment time that
   the record does not support is the one defect this product cannot ship. Numbers must survive
   translation, and every claim must come from the grounding bundle.
2. **Does the wrong person see the wrong data?** Four roles and many customers share one
   database. A customer reaching a staff surface, or another customer's ticket, is a breach.
3. **Does it stay up when a part of it does not?** Three models and an external LLM sit on the
   path. Each one has to be able to die without the customer losing their message.
4. **Is it fast enough to use?** An acknowledgement the customer waits for, and a page an agent
   opens forty times an hour.

Finding every defect is explicitly not the mission. The mission is to certify these four
properties and to leave a regression fence behind each one.

---

## 2. Target Test Items

| Item | Produced by | Why it is a target |
| --- | --- | --- |
| Edge (Caddy) and the gateway BFF | Us | Every request and every role check passes through both |
| auth (Better Auth, Node) | Us, on a third-party library | Sessions, sign-in throttling, role claims |
| inquiry | Us | The write the customer waits for; attachment storage |
| orchestrator | Us | Stage budgets, revisions, fan-in, the case record |
| triage (Groq or the distilled TriageModel) | Us, on Groq | Customer priority; must fall back when the model is slow or rate limited |
| grounding, response, knowledge | Us | What the reply may say, and the policy that holds it back |
| translation (NLLB-200 600M, CTranslate2) | Third-party model, our wrapper | Numbers, scripts, Sinhala conjuncts, fallback |
| audio (faster-whisper small) | Third-party model, our wrapper | Language detection, the 30 s budget |
| image (ONNX router classifier) | Ours, trained | Optional evidence; must not block the pipeline |
| business, payments, business-sim | Us | The ledger the reply quotes |
| control | Us | Live model rebinding without a restart |
| web (Next.js) | Us | Every screen on desktop and on a phone, and the wall between customer and back office |
| Monitoring (Prometheus, Grafana, exporters) | Us, on third-party tools | The operators' view of the VPS |
| Neon Postgres, TimescaleDB, MinIO, NATS, Valkey | Third party | Durability, round trip cost, message redelivery |
| compose stack and its overlays | Us | Every deployment shape the project ships |
| Deployment (Ansible, Terraform, GitHub Actions) | Us | A push to main has to reach the server |

Out of scope for this iteration: the MLOps profile (Airflow, MLflow, the weekly retrain) is
exercised by hand, not by this plan; browser coverage is Chromium only; and no penetration test
was commissioned.

---

## 3. Test Approach

Everything is tested through the interface a real user or a real operator has: the HTTP edge on
:8080 and the browser. No test reaches into a service's internals or a database directly, except
where a technique below says so. That choice costs some precision and buys the only thing that
matters here, which is that a passing suite means the product works, not that a function does.

**Where the tests run.** Development and production share one Neon database, so nothing that writes
runs against it. `compose.test.yaml` runs the complete stack on a throwaway Postgres, built from
scratch by the same migration and seed production uses; the resilience tests stop and start its
containers only. Production is exercised read only (`load/browse.js`).

**One command, in version control.** `bash scripts/test-plan.sh` runs every level below on the test
stack and keeps the evidence (logs, JUnit XML, k6 summaries, screenshots) in `reports/<date>/`. The
GitHub workflow `test-plan.yml` runs the same script on demand or weekly and uploads that folder.
CI's end to end job uses the same stack on every push.

Four levels, each with its own command:

| Level | What it covers | Command | Needs |
| --- | --- | --- | --- |
| Unit and contract | Pure logic: policy, fusion, confidence, translation guards, architecture rules | `bash scripts/test-all.sh` | Nothing |
| System | Function, access control, data integrity, performance, configuration | `uv run pytest tests/system -q` | The stack running |
| Browser | Screens, navigation, the customer and back office wall, every page on a 375 px phone | `cd web && npx playwright test` | The stack running |
| Scenario and load | The headline case end to end, hot model swap, sustained load | `scripts/demo_flow.py`, `scripts/verify_hot_swap.py`, `scripts/load.sh` | The stack running |

### 3.1 Testing Techniques and Types

#### 3.1.1 Data and Database Integrity Testing

**Objective.** Show that a write is durable and readable exactly as written, that a bad write is
refused, and that an id which does not exist produces a clean 404 rather than a leak or a 500.

**Technique.** Through the owning service's API, since each store is reached by exactly one
service and no test should be able to reach the database another way:

- Write a message with an unusual payload (Sinhala text, an amount, a time) and read it back from
  the conversation, comparing it character for character.
- Upload an attachment and fetch it back (MinIO round trip).
- Read the bill and check that each invoice's displayed total is the stored total formatted, so no
  screen can recompute money.
- Send an empty message, and an unknown id at every store-backed route.
- Check that a case revision is monotonic: a revision can only move forward.

**Oracles.** Self-verifying. The value written is the expected value, so the assertion is equality,
not a human reading a screen. For money the oracle is the ledger row, never a second computation
of the same figure.

**Required tools.** pytest and httpx (`tests/system/test_data_integrity.py`); `docker compose exec`
for a direct look when a failure needs explaining.

**Success criteria.** Every store-backed route is covered by at least one round trip and one
rejection, and all pass.

**Special considerations.** Neon is a shared database with seeded personas. Tests append and never
delete, so a run leaves the data larger but still correct. The duplicate guard in inquiry rejects
the same text twice within ten minutes, so every test message carries a timestamp.

#### 3.1.2 Function Testing

**Objective.** Exercise each use case through the same API the browser calls, with valid and
invalid input, and confirm the business rules.

**Technique.** One test per use case, driven by the persona who owns it:

- Public: plans and coverage without an account.
- Customer: overview, billing, usage, plan, notices, tickets, conversation.
- The headline case: a Sinhala message becomes a case, the case reaches a draft, and the draft
  comes back in Sinhala with every number intact.
- Staff: the console queue, a case with its evidence, approval, and the language override that
  re-runs the pipeline as a new revision.
- Admin: the model map, a live rebind, and the verification that the new binding answers.

**Oracles.** Mostly self-verifying: status codes, ids that match what was posted, a script check
(does the reply contain Sinhala characters), and a number-preservation check that compares the
digits in the English draft with the digits in the translated one. The quality of the wording is
not machine-checkable and is assessed by reading it; `scripts/demo_flow.py --strict` adds the one
machine check that matters, which is that the draft cites both the payment and the outage.

**Required tools.** pytest, httpx, `scripts/demo_flow.py`, `scripts/verify_hot_swap.py`.

**Success criteria.** Every use case in the plan has a test, and the headline case passes end to
end with a real model on the path, not a stub.

**Special considerations.** The pipeline is asynchronous: the acknowledgement returns in about a
second, the draft arrives fifteen to thirty seconds later. Tests poll with a budget rather than
sleep, and the budget is generous enough that a slow LLM is not reported as a failed test.

#### 3.1.3 User Interface Testing

**Objective.** Confirm that each screen renders the right data for the role that opened it, that
navigation goes where it says, and that nothing from the back office appears on a customer screen.

**Technique.** Playwright against the composed stack, never a dev server, because the edge is the
product:

- Sign in as each role and confirm where it lands and what it cannot reach.
- Open the console queue, open a case, see its draft.
- Open the model map, click a stage, see its verification panel.
- Walk every customer page and assert that none of a list of back office words appears
  (subscriber references, OLT, circuit ids, "grounding", "bundle", "LLM", "triage", "confidence",
  "null", "undefined", "NaN", and the em dash).
- Session persistence: a reload keeps the session and the landing page says who is signed in;
  signing out ends it and lands on the website.
- Mobile (`web/e2e/mobile.spec.ts`, project `mobile`): 26 pages across every role at 375 x 812 with
  touch. A page fails if it scrolls sideways, and the message names the element that sticks out;
  each page is kept as a screenshot for a person to review.

**Oracles.** Self-verifying through roles and accessible names rather than CSS selectors, so a test
breaks when the meaning changes and not when the styling does. Visual appearance is out of scope
for automation and is reviewed by hand.

**Required tools.** Playwright (Chromium, desktop and a Pixel 7 profile narrowed to 375 px), `web/e2e/*.spec.ts`.

**Success criteria.** Every major screen is opened by a test, and the customer immersion check
covers every customer page.

**Special considerations.** The live updates stream stays open for as long as a page is open, so
`networkidle` never arrives; tests wait for content, not for silence. Sign-in is rate limited per
address, so the helper backs off and retries.

#### 3.1.4 Performance Profiling

**Objective.** Measure the two latencies a person actually waits for, and fence them against
regression: the acknowledgement after pressing send, and a page an agent opens repeatedly.

**Technique.** A single user, warm connection, five samples per route, median compared against a
budget. The budgets sit above the current best measurement and below the point where the screen
feels slow, so they catch a regression without failing on noise.

| Route | Budget (median) |
| --- | --- |
| `/api/me` | 800 ms |
| `/api/app/overview` | 1500 ms |
| `/api/app/billing`, `/api/app/plan`, `/api/app/notices` | 800 ms |
| `/api/app/usage` | 1200 ms |
| Message acknowledgement | 2500 ms |
| Console queue | 3000 ms |

**Oracles.** Self-verifying, with the measured median printed on failure.

**Required tools.** pytest (`tests/system/test_performance.py`), `scripts/neon-latency.py` for the
database round trip that dominates every one of these numbers.

**Success criteria.** Every budget met on a warm stack.

**Special considerations.** The database is the whole story: from Colombo, one round trip to the
Neon project in Ohio is about 320 ms, and most of these routes need one or two. The move to
Singapore is scripted in `scripts/neon-move.sh`. Measurements taken on a laptop that is also
running the sixteen services are not a server benchmark and are not presented as one.

#### 3.1.5 Load Testing

**Objective.** Confirm the system holds a sustained arrival rate without errors, and record where
latency lands under that load.

**Technique.** k6, constant arrival rate of 5 inquiries a second for one minute, up to 20 virtual
users, each iteration sending a message and reading the account overview. Thresholds from the
build plan: the acknowledgement p50 under 300 ms and p95 under 800 ms, the overview p50 under
250 ms, and a failure rate under 1 percent.

**Oracles.** k6 thresholds, which fail the run by exit code.

A second scenario, `load/browse.js`, is read only and safe on production: 20 concurrent users
(ramped over a minute, held for three) loading the landing page, the catalogue and a signed-in
customer's overview, billing and tickets, with page p95 under 2 s and API p95 under 1.5 s. The
Grafana dashboard is watched during the run.

**Required tools.** `scripts/load.sh` (k6 locally, or the grafana/k6 image); `SCRIPT=load/browse.js`
for the production scenario.

**Success criteria.** Zero failed requests, and the latency thresholds met once the database is in
the same region as the application.

**Special considerations.** Run on a dedicated machine for a number worth quoting. Everything in
this iteration was run on the development laptop, which also hosts the models.

#### 3.1.6 Security and Access Control Testing

**Objective.** Application level: no role reaches a surface that is not its own, and no customer
reaches another customer's row. System level: a session cannot be forged or replayed.

**Technique.**

- Every staff route with no token at all: expect 401.
- Every staff route with a valid customer token: expect 403.
- Admin-only routes with a valid agent token: expect 403.
- Each role against its own surface: expect 200.
- Two customers, each fetching the other's ticket by id: expect 403 or 404, never the row.
- A token with its signature altered: expect 401.
- A wrong password: rejected, and repeated attempts throttled.
- The repository: gitleaks on every push, so a credential cannot reach the history.

**Oracles.** Self-verifying by status code, which is the whole assertion: the test fails if the
body ever arrives.

**Required tools.** pytest (`tests/system/test_access_control.py`), gitleaks in CI.

**Success criteria.** Every staff and admin route is covered by both the unauthenticated and the
wrong-role case.

**Special considerations.** The client-side role gate is a convenience; the gateway is the control.
Tests therefore assert against the API, and the browser test only confirms the gate is wired.

#### 3.1.7 Failover and Recovery Testing

**Objective.** Show that each optional stage can be dead without the customer losing their message,
and that a restarted service rejoins on its own.

**Technique.** Stop one container, drive a real message through, restart it, and check the map:

- translation stopped: the case still opens and still reaches a draft (the reply comes through in
  English rather than not at all).
- audio stopped: the message is still accepted.
- grounding stopped: the model map reports it down rather than claiming health.
- translation restarted: the map reports it up again with no other action.
- the triage language model fails, times out (2 s) or is rate limited: the distilled TriageModel
  scores the case instead, and its reasons say why (unit tests force each path).

**Oracles.** Self-verifying: the case exists, the draft exists, and the map's status field.

**Required tools.** pytest with `LANKA_RESILIENCE=1` (`tests/system/test_resilience.py`), which
stops and starts containers and always restores them.

**Success criteria.** No message is lost in any single-service outage, and recovery needs no
manual step.

**Special considerations.** These tests are destructive and are excluded from the default run. The
LLM has its own failover inside the product (a primary binding, a fallback binding and a circuit
breaker), which is covered separately by the hot swap script.

#### 3.1.8 Configuration Testing

**Objective.** Every deployment shape the project ships must be valid and complete before anyone
tries to run it.

**Technique.**

- `docker compose config -q` for each overlay: base, lite, CI, GPU, production, test, CI with test,
  and production with monitoring.
- The whole stack starts from an empty database on every run of the plan.
- The mlops profile must add both Airflow and MLflow.
- Every variable the compose files read must exist in `.env.example`, so a fresh deployment cannot
  start and then fail at runtime on a missing key.

**Oracles.** Self-verifying: exit code, and a diff of variable names.

**Required tools.** pytest (`tests/system/test_configuration.py`), Docker.

**Success criteria.** All overlays valid, no variable missing. This is the one technique that runs
without the stack, so it also runs in CI on every pull request.

---

## 4. Deliverables

### 4.1 Test Evaluation Summaries

`docs/TEST-RESULTS.md` records each run: what was executed, the counts, the measurements, and
every defect the run found, with its cause and its fix. It is written per test run and kept in the
repository beside the code it describes.

### 4.2 Reporting on Test Coverage

Coverage is reported by requirement rather than by line, because the risk here is a missing
conversation, not a missing branch:

| Technique | Where | Count |
| --- | --- | --- |
| Unit and contract | `packages`, `services/*/tests`, `tests/architecture` | 131 tests, 2 Node tests, 6 module self-checks |
| Data and database integrity | `tests/system/test_data_integrity.py` | 8 |
| Function | `tests/system/test_functional.py` | 6, plus 2 scenario scripts |
| Access control | `tests/system/test_access_control.py` | 15 |
| Performance | `tests/system/test_performance.py` | 8 |
| Configuration | `tests/system/test_configuration.py` | 10 |
| Failover and recovery | `tests/system/test_resilience.py` | 4 |
| User interface | `web/e2e` | 16 (11 desktop, 5 mobile covering 26 pages) |
| Load | `load/ack.js`, `load/browse.js` | 2 scenarios, 7 thresholds |

CI runs everything that needs no containers on every pull request, and the end to end job (the
CI stack on the test database: smoke, hot swap, scenario, browser, load) on every push.

---

## 5. Risks, Dependencies, Assumptions, and Constraints

| Risk | Impact | What we do about it |
| --- | --- | --- |
| The database is far from the server | Every round trip is in every page timing | Moved to Singapore (46 ms from Colombo); production is measured separately from the test stack |
| Tests writing into production data | Test tickets, suspended accounts and load in the live database | Every writing test runs on `compose.test.yaml`; only the read-only scenario touches production |
| External model capacity | Groq's free tier allows 8,000 tokens a minute; Ollama Cloud drafts about eight a minute | Triage falls back to its own model; a missed draft leaves the case with the agent, never loses it |
| The drafting model is a cloud LLM | An outage or a 503 fails the draft stage, which looks like a product defect | The binding has a fallback and a circuit breaker; the held message names both errors; `verify_hot_swap.py` proves the switch works |
| Model behaviour is not deterministic | The same message does not produce the same words twice | Tests assert on structure and on facts (script, numbers, citations), never on wording |
| Measurements come from a development laptop | The numbers are not a server benchmark | Every figure in the results says where it was taken |
| Browser coverage is Chromium only | A Safari or Firefox defect would not be caught | Accepted for this iteration |
| Sinhala and Tamil correctness is judged by a small number of readers | A subtle mistranslation can pass | The machine checks cover what can be checked (numbers, script, conjuncts); wording is reviewed by a native reader |
| No Sinhala voice sample was available | Speech is proven for English only | Recorded as a gap; a Sinhala clip is needed to close it |

**Dependencies.** Docker Desktop; a Neon project; an Ollama daemon signed in for the cloud model,
with a Gemini key as the fallback; the model weights (NLLB and Whisper) inside the images.

**Assumptions.** The seeded personas and passwords from `.env.example` exist in the database; the
edge is reachable on :8080; the machine has enough memory to hold both models resident.

**Constraints.** One iteration, one team, no dedicated test environment and no dedicated test
hardware.

---

## 6. References

- `PLAN.md`: the build plan this system was written against, including its latency budgets.
- `docs/TEST-RESULTS.md`: the evaluation summary for each run.
- `docs/DEPLOYMENT.md`: how the tested artefact reaches a server.
- Rational Unified Process, Master Test Plan template, which this document follows.
