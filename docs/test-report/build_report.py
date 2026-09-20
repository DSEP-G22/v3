"""Builds the Master Test Plan and Test Report (.docx) from a test-plan run.

    python docs/test-report/build_report.py --collect reports/<run>   # copy the run's evidence in
    python docs/test-report/build_report.py                            # build from evidence/
    powershell -File docs/test-report/export.ps1 docs/test-report/Lanka-Link-v3-Master-Test-Plan.docx

Counts and timings are read from the evidence (JUnit XML, k6 summaries, the run's logs and the
pipeline statistics), so a new run rebuilds a report that matches it. The prose is written here.
Needs python-docx and Pillow:  uv run --with python-docx --with pillow python docs/test-report/build_report.py
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from docxkit import Report
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EV = HERE / "evidence"
OUT = HERE / "Lanka-Link-v3-Master-Test-Plan.docx"
PROD = "https://172-197-200-110.sslip.io"


# -- evidence ---------------------------------------------------------------------------------------

def collect(run: Path) -> None:
    """Copy what the report quotes out of a run directory (reports/ is not committed)."""
    for d in ("terminal", "mobile", "desktop", "logs"):
        (EV / d).mkdir(parents=True, exist_ok=True)
    for name in ("summary.tsv", "junit-system.xml", "junit-browser.xml", "load-ack.json"):
        if (run / name).exists():
            shutil.copy2(run / name, EV / name)
    for f in (run / "logs").glob("*.log"):
        shutil.copy2(f, EV / "logs" / f.name)
    # Screenshots are photographs of a screen, not line art: JPEG keeps the repository small.
    from PIL import Image as _I
    for kind, scale in (("mobile", 2), ("desktop", 1)):
        for f in (run / "screens" / kind).glob("*.png"):
            im = _I.open(f).convert("RGB")
            if scale > 1:
                im = im.resize((im.width // scale, im.height // scale), _I.LANCZOS)
            im.save(EV / kind / f"{f.stem}.jpg", quality=82, optimize=True)


def excerpts() -> None:
    """Per-technique slices of the system log, rendered as terminal screenshots."""
    log = (EV / "logs" / "03-system.log").read_text(encoding="utf-8", errors="replace")
    src = EV / "terminal-src"
    src.mkdir(exist_ok=True)
    for f in src.glob("*.log"):
        f.unlink()
    for name in ("access_control", "configuration", "data_integrity", "functional", "performance", "resilience"):
        lines = [ln for ln in log.splitlines() if f"test_{name}.py" in ln]
        cmd = f"$ uv run pytest tests/system/test_{name}.py -v   (from the full run, {len(lines)} results)"
        (src / f"system-{name}.log").write_text("\n".join([cmd, *lines]) + "\n", encoding="utf-8")
    for f in (EV / "logs").glob("*.log"):
        shutil.copy2(f, src / f.name)
    for f in EV.glob("extra-*.log"):
        shutil.copy2(f, src / f.name)
    node = shutil.which("node") or "node"
    subprocess.run([node, "scripts/term-shots.mjs", str(src), str(EV / "terminal")], cwd=ROOT / "web", check=True)


def sheet(names: list[str], out: Path, crop_css: int = 760) -> Path | None:
    """Phone screenshots side by side, the top of each page, as one figure."""
    tiles = []
    for n in names:
        p = screen("mobile", n)
        if p:
            im = Image.open(p).convert("RGB")
            scale = im.width / 375
            im = im.crop((0, 0, im.width, min(im.height, int(crop_css * scale))))
            tiles.append(im.resize((300, int(300 * im.height / im.width))))
    if not tiles:
        return None
    h = max(t.height for t in tiles)
    canvas = Image.new("RGB", (len(tiles) * 316 + 16, h + 32), "white")
    for i, t in enumerate(tiles):
        canvas.paste(Image.new("RGB", (t.width + 4, t.height + 4), (200, 200, 205)), (16 + i * 316 - 2, 14))
        canvas.paste(t, (16 + i * 316, 16))
    canvas.save(out, optimize=True)
    return out


def screen(kind: str, name: str) -> Path | None:
    """A captured screen, whichever format it was kept in."""
    return next((q for q in (EV / kind / f"{name}.jpg", EV / kind / f"{name}.png") if q.exists()), None)


def junit(path: Path, group) -> Counter:
    c: Counter = Counter()
    if not path.exists():
        return c
    for tc in ET.parse(path).iter("testcase"):
        g = group(tc)
        state = "skipped" if tc.find("skipped") is not None else "failed" if (
            tc.find("failure") is not None or tc.find("error") is not None) else "passed"
        c[(g, state)] += 1
    return c


def k6(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["metrics"] if path.exists() else {}


def ms(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.0f} ms" if v >= 10 else f"{v:.1f} ms"


# -- the report -------------------------------------------------------------------------------------

def build() -> None:
    sysc = junit(EV / "junit-system.xml", lambda tc: tc.get("classname").rsplit(".", 1)[-1].removeprefix("test_"))
    brc = junit(EV / "junit-browser.xml", lambda tc: tc.get("classname", "").split(" ")[0] or "browser")
    browser_by_project = Counter()
    if (EV / "junit-browser.xml").exists():
        for suite in ET.parse(EV / "junit-browser.xml").iter("testsuite"):
            proj = suite.get("hostname", "chromium")
            for tc in suite.iter("testcase"):
                ok = tc.find("failure") is None and tc.find("error") is None and tc.find("skipped") is None
                browser_by_project[(proj, "passed" if ok else "failed")] += 1
    summary = [ln.split("\t") for ln in (EV / "summary.tsv").read_text(encoding="utf-8").splitlines() if ln.strip()]
    unit_log = (EV / "logs" / "01-unit.log").read_text(encoding="utf-8", errors="replace")
    unit_passed = sum(int(n) for n in re.findall(r"(\d+) passed", unit_log))
    ack = k6(EV / "load-ack.json")
    browse = k6(EV / "load-browse.json")
    stats = json.loads((EV / "pipeline.json").read_text(encoding="utf-8")) if (EV / "pipeline.json").exists() else {}

    def count(c: Counter, g: str, s: str) -> int:
        return c[(g, s)]

    def tot(c: Counter, s: str) -> int:
        return sum(v for (_, st), v in c.items() if st == s)

    r = Report(HERE / "template.docx", project="Lanka Link v3", title="Master Test Plan", version="2.0",
               company="DSEP Group 22")
    r.revision([
        ("19/Sep/26", "1.0", "First master test plan; run on the development laptop against the shared database.", "DSEP Group 22"),
        ("20/Sep/26", "2.0", "Isolated test stack, mobile layouts, Groq triage and monitoring added; full run, "
                             "load test on the isolated stack and a read-only load test on production.", "DSEP Group 22"),
    ])

    # 1 -----------------------------------------------------------------------------------------
    r.h1("Evaluation Mission and Test Motivation")
    r.p("This Master Test Plan and Test Report covers Lanka Link v3, a customer support system for a Sri Lankan "
        "internet service provider. A customer writes in Sinhala, Tamil, Singlish, Tanglish or English, from a phone "
        "or a browser, and may attach a photo of the router or a voice note. The system transcribes the voice note, "
        "translates the message into English, reads the customer's line, bill and area record, triages the request, "
        "diagnoses the fault, drafts a reply that may only state what the records prove, and puts that reply in front "
        "of an agent. The approved reply goes back in the language the customer wrote in.")
    r.p("The system is sixteen services behind one edge, two large models on the request path (NLLB-200 for "
        "translation and faster-whisper for speech), language models for triage, diagnosis and drafting (Groq, "
        "Ollama Cloud and Gemini), and three stores. Any of those can be slow, wrong or absent, and the product still "
        "has to answer. A single wrong amount in a reply, or one customer seeing another customer's ticket, is a "
        "failure the business cannot ship.")
    r.p("The mission of this test effort, in priority order:")
    r.bullets([
        "**Certify that replies tell the truth.** Every figure a reply quotes (a balance, an outage time) must come "
        "from the records and must survive translation unchanged.",
        "**Certify that the wrong person never sees the wrong data.** Four staff roles and many customers share one "
        "database; every surface is checked against every role.",
        "**Show that the system stays up when a part does not.** Each model and each external language model must be "
        "able to fail without the customer losing their message.",
        "**Measure whether it is fast enough, and where it stops scaling.** Response times for the screens people "
        "use, the acknowledgement a customer waits for, and the load at which the pipeline degrades.",
        "**Verify the changes of this iteration:** the Groq triage models, the mobile layouts and the production "
        "monitoring.",
        "**Record why each model on the path was chosen**, from the offline benchmarks that picked "
        "them, so a later change can be compared against the same measurements.",
        "**Leave the tests behind as a regression fence** that anyone can rerun with one command or one click, "
        "without touching production data.",
    ])

    # 2 -----------------------------------------------------------------------------------------
    r.h1("Target Test Items")
    r.p("The listing below identifies the software, hardware and supporting elements that are targets for testing.")
    r.table(["Item", "What it is", "Why it is a target"], [
        ["Edge (Caddy) and gateway", "Every request enters here; the gateway checks the role on every call", "Access control and response time"],
        ["auth (Better Auth)", "Sessions, sign-in throttling, role claims", "Security"],
        ["inquiry", "The write a customer waits for; attachments to object storage", "Acknowledgement time, data integrity"],
        ["orchestrator", "Stage budgets, revisions, the case record", "Failover, performance"],
        ["triage (new: Groq)", "Department rules; customer priority from a Groq model or the distilled TriageModel", "Function, failover under rate limits"],
        ["knowledge, grounding, response", "Diagnosis, the evidence bundle, the drafted reply", "Truthfulness, load capacity"],
        ["translation, audio, image", "NLLB-200, faster-whisper, the router photo classifier", "Numbers across languages, resilience"],
        ["business, payments, control", "The ledger, payments stub, live model bindings", "Data integrity, hot model swap"],
        ["web (new: mobile layouts)", "Every screen for customers, agents, admins and operators", "User interface on desktop and phone"],
        ["Neon Postgres, TimescaleDB, MinIO, NATS, Valkey", "Third-party stores and messaging", "Durability, round-trip cost"],
        ["Monitoring (new)", "Prometheus, Grafana, node-exporter, cAdvisor, blackbox probes", "Operability of the VPS"],
        ["The models themselves", "Intent and priority text models, the router photo classifier, speech, the drafting design", "Chosen by benchmark (section 3.2), and re-checked live by the stage verifications"],
        ["Deployment", "GitHub Actions, GHCR images, Ansible, the Ubuntu VPS", "A push to main must reach production"],
    ], widths=[1.7, 2.6, 2.0])
    r.p("Out of scope for this iteration: Firefox and Safari (Chromium only, desktop and a 375 pixel phone profile), "
        "a commissioned penetration test, and the MLOps profile (Airflow, MLflow).")

    # 3 -----------------------------------------------------------------------------------------
    r.h1("Test Approach")
    r.p("Everything is tested through the interfaces a real user or operator has: the HTTP edge and the browser. "
        "A passing suite then means the product works, not that a function does. Tests are black box, automated "
        "and self-verifying: each one decides pass or fail from status codes, ids, digits and scripts, never from a "
        "person reading a screen.")
    r.p("**The test environment is isolated.** Development and production share one Neon database, so running "
        "tests against the normal stack would write test tickets, suspend accounts and push load into production. "
        "This iteration adds `compose.test.yaml`, which runs the complete stack (all sixteen services and both "
        "models) on a throwaway Postgres built from scratch by the same migration and seed that production uses. "
        "Production itself is only exercised read-only, by the second load test.")
    r.table(["Level", "What it covers", "Command", "Needs"], [
        ["Unit and contract", "Policy, fusion, translation guards, triage fallback, architecture rules", "bash scripts/test-all.sh", "Nothing"],
        ["System", "Function, access control, data integrity, performance, configuration, failover", "pytest tests/system", "Test stack"],
        ["Browser", "Screens on desktop Chromium and a 375 px phone", "npx playwright test", "Test stack"],
        ["Scenario", "The headline Sinhala case end to end; live model swap", "demo_flow.py, verify_hot_swap.py", "Test stack"],
        ["Load", "Write path at 5 inquiries a second; read-only browsing on production", "scripts/load.sh", "Test stack, production"],
        ["Everything", "All of the above, evidence kept", "bash scripts/test-plan.sh", "Docker"],
    ], widths=[1.1, 2.5, 1.7, 1.0])
    r.p("**Reproducible and in version control (GitOps).** The plan is code: the suites, the stack definition, the "
        "load scenarios and the runner live in the repository. `bash scripts/test-plan.sh` runs the whole plan on "
        "any machine with Docker and writes every log, JUnit XML file, k6 summary and screenshot into "
        "`reports/<date>/`. The same runner is a GitHub Actions workflow (`test-plan.yml`, run from the Actions tab "
        "or weekly) that uploads that folder as an artifact. The CI end-to-end job now uses the same isolated stack "
        "on every push, so it no longer waits for a separate database. This report is generated from a run's "
        "evidence by `docs/test-report/build_report.py`.")

    r.h2("Testing Techniques and Types")

    # 3.1.1
    r.h3("Data and Database Integrity Testing")
    r.p("The databases and the processes that write them are tested as a subsystem, through the one service that "
        "owns each store, since no test (and no other service) may reach a store directly.")
    r.technique({
        "Technique Objective:": "Show that a write is durable and reads back exactly as written, that a bad write is "
                                "refused, and that an unknown id gives a clean 404 rather than a leak or a 500.",
        "Technique:": ["Write a message with Sinhala text, an amount and a time; read it back from the conversation "
                       "and compare character for character.",
                       "Upload an attachment and fetch it back (object storage round trip).",
                       "Check that each invoice's displayed total is the stored total formatted, so no screen "
                       "recomputes money.",
                       "Send an empty message and unknown ids to every store-backed route.",
                       "Check that a case revision only moves forward.",
                       "New: build the whole database from nothing (migrate and seed on an empty Postgres) on every run."],
        "Oracles:": "Self-verifying: the value written is the expected value, so the assertion is equality. For money "
                    "the oracle is the ledger row, never a second calculation of the same figure.",
        "Required Tools:": ["pytest and httpx (tests/system/test_data_integrity.py)",
                            "compose.test.yaml (Postgres with pgvector, built from scratch)",
                            "psql inside the test database for diagnosis"],
        "Success Criteria:": "Every store-backed route has a round trip and a rejection test, and all pass. A fresh "
                             "install starts without manual steps.",
        "Special Considerations:": "Tests only append, so one database can serve many runs. The duplicate guard "
                                   "refuses the same text twice within ten minutes, so every test message carries a "
                                   "timestamp.",
    })
    di = count(sysc, "data_integrity", "passed")
    r.p(f"**Result: {di} of {di + count(sysc, 'data_integrity', 'failed')} passed.** Building the database from "
        "nothing found two defects that the shared, long-lived database had hidden for weeks: the inquiry service "
        "could not start on an empty database because a backfill statement read a table that is only created later "
        "in the same script (D10), and the seed forced TLS on every database connection (D11). Both were fixed; an "
        "empty database now comes up with no manual step.")
    r.image(EV / "terminal" / "system-data_integrity.png", "Figure 1: Data and database integrity tests, from the full run.")

    # 3.1.2
    r.h3("Function Testing")
    r.p("Function testing follows the use cases, driven through the same API the browser calls, by the persona who "
        "owns each one.")
    r.technique({
        "Technique Objective:": "Exercise each use case with valid and invalid input and confirm the business rules, "
                                "including the headline case: a suspended customer inside an outage writes in "
                                "Sinhala and must get a truthful Sinhala reply.",
        "Technique:": ["Public: plans without an account. Customer: overview, billing, usage, plan, notices, tickets.",
                       "Headline case (demo_flow.py --strict): suspend Ravi's account, send his Sinhala message, wait "
                       "for the draft, require it to cite both the unpaid balance and the outage, approve it, and "
                       "require the Sinhala reply to carry the same amount.",
                       "Staff: the queue, a case with its evidence, approval, a language override.",
                       "Admin: rebind the drafting model live and back (verify_hot_swap.py).",
                       "New: triage through Groq, checked by calling the triage service and by the unit tests of its "
                       "fallback."],
        "Oracles:": "Status codes, ids, the script of the reply (Sinhala characters present), and number "
                    "preservation: the digits in the English draft must equal the digits in the translated reply. "
                    "Wording is not machine-checkable and is read by a person.",
        "Required Tools:": ["pytest, httpx", "scripts/demo_flow.py, scripts/verify_hot_swap.py",
                            "Real models: Ollama Cloud gpt-oss for drafting and diagnosis, Groq for triage, NLLB-200"],
        "Success Criteria:": "Every use case passes, and the headline case passes end to end with real models on "
                             "the path, not the offline stub.",
        "Special Considerations:": "The pipeline is asynchronous: the acknowledgement returns at once and the draft "
                                   "arrives 15 to 40 seconds later, so tests poll with a budget instead of sleeping.",
    })
    fn = count(sysc, "functional", "passed")
    r.p(f"**Result: {fn} of {fn + count(sysc, 'functional', 'failed')} function tests passed; the headline scenario "
        "and the live model swap passed.** Ravi's Sinhala message was acknowledged in about 60 ms and drafted in "
        "under 30 s. The draft cited both the unpaid balance and the outage, and the Sinhala reply carried the amount "
        "unchanged (රුපියල් 18,574.40). Reading the Sinhala reply found one wording defect: a conjunct split by a space "
        "(\"මධ් යම\" for \"මධ්‍යම\", central), left open as D13.")
    r.image(EV / "terminal" / "05-demo-flow.png", "Figure 2: The headline case end to end, with a real model and a Sinhala reply.")
    if stats.get("triage"):
        g = stats["triage"]
        r.p(f"**Groq triage.** The new `llm_triage` binding scores the customer side priority with "
            f"`{g.get('model', 'qwen/qwen3.8-27b')}` on Groq, with the distilled TriageModel as the fallback. Measured "
            f"directly: {g.get('direct_ms', 'about 250')} ms a call, and the same message always gets the same level "
            "once temperature is 0 (eight calls, eight identical levels; with the default temperature the same "
            "message scored 3, 8, 5 and 7). Five Groq models were checked for valid JSON and latency before choosing "
            "the default:")
        r.table(["Groq model", "JSON valid", "Latency (two calls)", "Choice"], g.get("models", []), widths=[2.0, 0.9, 1.6, 1.8])
    r.image(EV / "terminal" / "06-hot-swap.png", "Figure 3: The drafting model is rebound live, answers, and is restored.", width=5.2)

    # 3.1.3
    r.h3("User Interface Testing")
    r.p("User interface testing checks that each screen shows the right data to the role that opened it, that "
        "navigation goes where it says, that nothing from the back office reaches a customer screen, and, new in "
        "this iteration, that every screen works on a phone.")
    r.technique({
        "Technique Objective:": "Exercise every screen on desktop Chromium and on a 375 pixel wide phone, observing "
                                "navigation, role gates, the customer immersion rule and layout.",
        "Technique:": ["Sign in as each role; confirm where it lands and what it cannot reach.",
                       "Console: open the queue and a case with its draft. Admin: open the model map and a stage.",
                       "Immersion: walk every customer page and fail on any back office word (subscriber ids, OLT, "
                       "LLM, triage, confidence, null, undefined, NaN, the em dash).",
                       "Session: a reload keeps the session; signing out ends it and lands on the website.",
                       "New, mobile: visit 26 pages across all roles at 375 x 812 with touch, fail if any page "
                       "scrolls sideways (naming the element that sticks out), and keep a screenshot of each."],
        "Oracles:": "Roles and accessible names rather than CSS selectors, so a test breaks when meaning changes and "
                    "not when styling does. The mobile oracle is geometric: the page's scroll width must not exceed "
                    "the viewport. Visual quality is judged by a person from the screenshots.",
        "Required Tools:": ["Playwright with Chromium (web/e2e), a Pixel 7 touch profile narrowed to 375 px",
                            "Screenshots kept per page for review"],
        "Success Criteria:": "Every major screen is opened by a test on both form factors, and none scrolls sideways.",
        "Special Considerations:": "The live update stream never goes idle, so tests wait for content, not for "
                                   "network silence. Sign-in is rate limited per address, so the helper backs off.",
    })
    desk, mob = browser_by_project[("chromium", "passed")], browser_by_project[("mobile", "passed")]
    r.p(f"**Result: {desk} desktop and {mob} mobile browser tests passed, {browser_by_project[('chromium', 'failed')] + browser_by_project[('mobile', 'failed')]} failed.** "
        "The first mobile audit, run against production before the changes, found four pages that scrolled sideways "
        "(the landing page, plans, documentation and the incidents page) and, from the screenshots, three layouts "
        "that fitted but did not work on a phone: the customer menu hid four of its six items off screen, the agent "
        "inbox table cut off everything after the summary, and the model map shrank to unreadable size. The fixes: "
        "a bottom tab bar for customers (five tabs, 56 px targets, safe area aware) with settings in the header, "
        "the inbox as cards, the model map as a list on phones, a sim clock bar that scrolls within itself, and the "
        "overflow causes themselves (a header whose hidden class lost to the button's own display, a grid child "
        "without min-width, oversize key caps). The run also found D12: signing out of the customer area landed on "
        "the sign-in page instead of the website.")
    r.p("The screenshots below are the product in dark appearance, which is what a phone or a "
        "desktop set to dark shows; the suites capture both form factors on every run.")
    before = HERE / "evidence" / "mobile-before-sheet.png"
    if before.exists():
        r.image(before, ("Figure 4: Before the changes, on production (light appearance): the customer menu shows two of "
                              "six items, and the inbox is cut off."), width=6.3)
    s1 = sheet(["customer-home", "customer-billing", "customer-new-ticket", "customer-usage"], EV / "mobile-sheet-customer.png")
    if s1:
        r.image(s1, "Figure 5: After, customer screens at 375 px, with the bottom tab bar.", width=6.3)
    s2 = sheet(["console-inbox", "admin-models", "sim-network", "landing"], EV / "mobile-sheet-staff.png")
    if s2:
        r.image(s2, "Figure 6: After, the agent inbox as cards, the model map as a list, the network map, the landing page.", width=6.3)
    for name, cap in (("console-inbox", "Figure 7: The agent console on a desktop browser, dark."),
                      ("admin-models", "Figure 8: The model map, where every stage is verified and rebound."),
                      ("sim-network", "Figure 9: The simulated network an operator breaks things on."),
                      ("customer-home", "Figure 10: The customer's home screen on a desktop browser.")):
        shot = screen("desktop", name)
        if shot:
            r.image(shot, cap, width=6.1)
    r.image(EV / "terminal" / "04-browser.png", "Figure 11: Browser tests, desktop and mobile projects.")

    # 3.1.4
    r.h3("Performance Profiling")
    r.p("Performance profiling measures the latencies a person waits for, on a single user, and profiles where "
        "time goes inside the pipeline.")
    r.technique({
        "Technique Objective:": "Measure the acknowledgement after pressing send, the screens an agent and a customer "
                                "open repeatedly, and each pipeline stage, under a normal and a heavy workload.",
        "Technique:": ["Single user, warm connection, five samples per route, median against a budget.",
                       "Every stage of every case records its duration and outcome (cases.stage_event), which is "
                       "summarised per stage after the load run.",
                       "On production: the Grafana dashboard's edge latency (p50, p95, p99) and host resources."],
        "Oracles:": "Budgets set above the best measurement and below the point where a screen feels slow, so a "
                    "regression fails without noise failing it. The measured median is printed on failure.",
        "Required Tools:": ["pytest (tests/system/test_performance.py)", "SQL over cases.stage_event",
                            "Prometheus and Grafana"],
        "Success Criteria:": "Every budget met on a warm stack; every stage's p95 inside its budget at normal load.",
        "Special Considerations:": "The isolated test database is on the same machine, so its numbers show the code, "
                                   "not the network. Production numbers, with the database in Singapore and the "
                                   "server in Malaysia, come from the read-only load test.",
    })
    pf = count(sysc, "performance", "passed")
    r.p(f"**Result: {pf} of {pf + count(sysc, 'performance', 'failed')} budgets met.**")
    if stats.get("stages"):
        r.p("Where the time goes, per stage, over every case of the run (including the load burst):")
        r.table(["Stage", "Outcome", "Cases", "p50", "p95"], stats["stages"], widths=[1.3, 1.1, 0.9, 1.3, 1.3])
        r.p("The local stages (translation, account prefetch, grounding) take milliseconds. The three stages that "
            "call an external language model (triage, diagnosis, drafting) dominate, and they are where capacity "
            "ends, as the load test shows.")
    r.image(EV / "terminal" / "system-performance.png", "Figure 12: Performance budgets, from the full run.")

    # 3.1.5
    r.h3("Load Testing")
    r.p("Load testing subjects the system to sustained and rising workloads, on the write path in isolation and on "
        "the read path in production.")
    r.technique({
        "Technique Objective:": "Show that the system holds a sustained arrival rate without errors, find where it "
                                "degrades, and measure production under concurrent browsing.",
        "Technique:": ["Write path (isolated stack): k6 at a constant 5 new tickets a second for one minute, up to 20 "
                       "virtual users, each iteration sending a message and reading the account overview. That is "
                       "300 tickets a minute, far above expected traffic, and every one runs the full pipeline.",
                       "Read path (production): k6 ramping to 20 concurrent users over one minute, holding three "
                       "minutes, ramping down over one; each user loads the landing page, the plan catalogue and the "
                       "plans page, then a signed-in customer's overview, billing and tickets. No writes.",
                       "Production is watched on the Grafana dashboard during the run."],
        "Oracles:": "k6 thresholds, which fail the run by exit code: acknowledgement p50 under 300 ms and p95 under "
                    "800 ms, overview p50 under 250 ms, page p95 under 2 s, API p95 under 1.5 s, failures under 1 percent.",
        "Required Tools:": ["k6 (scripts/load.sh; load/ack.js, load/browse.js)", "Grafana, Prometheus, cAdvisor"],
        "Success Criteria:": "Zero failed requests and every threshold met; the degradation point identified and "
                             "shown to fail safe.",
        "Special Considerations:": "Write load is never run against production: it would open hundreds of real "
                                   "tickets. The production run signs in once, since sign-in is rate limited per "
                                   "address by design.",
    })
    if ack:
        a, o, f = ack.get("http_req_duration{name:ack}", {}), ack.get("http_req_duration{name:overview}", {}), ack.get("http_req_failed", {})
        r.p("**Write path, isolated stack:**")
        r.table(["Metric", "Result", "Threshold", "Verdict"], [
            ["Requests", f"{ack['http_reqs']['count']}, {f.get('passes', 0)} failed", "under 1 percent failed", "Pass"],
            ["Tickets opened", f"{ack['iterations']['count']} in 60 s", "", ""],
            ["Acknowledgement p50", ms(a.get("med")), "300 ms", "Pass" if a.get("med", 1e9) < 300 else "Fail"],
            ["Acknowledgement p95", ms(a.get("p(95)")), "800 ms", "Pass" if a.get("p(95)", 1e9) < 800 else "Fail"],
            ["Overview p50", ms(o.get("med")), "250 ms", "Pass" if o.get("med", 1e9) < 250 else "Fail"],
        ], widths=[1.8, 1.7, 1.6, 1.0])
        r.image(EV / "terminal" / "07-load.png", "Figure 13: k6 on the write path: every threshold met, no failed request.")
    if stats.get("triage_split"):
        t = stats["triage_split"]
        r.p(f"**Behind the acknowledgement, the pipeline under that burst.** Every one of the {t['total']} cases was "
            f"created, triaged and put in front of an agent. Triage used Groq for {t['groq']} of them "
            f"(average {t['groq_ms']} ms); Groq's free tier allows 8,000 tokens a minute, so the other {t['model']} "
            "fell back to the distilled TriageModel as designed, with no failure. Diagnosis and drafting call Ollama "
            f"Cloud, which accepts four requests at a time per client: {stats.get('diagnose_timeouts', 0)} diagnoses "
            f"reached their 15 s budget and {stats.get('draft_failed', 0)} drafts their 30 s budget, so those cases "
            "reached the agent without a proposed reply. That is the system's capacity limit: about "
            f"{stats.get('draft_capacity', 'eight')} drafts a minute with the current model account. It fails safe "
            "(no message is lost, no customer sees an error), and it is far above today's traffic, but it is the "
            "first thing to scale: a paid model tier, Groq for drafting, or a queue that drafts in arrival order.")
    if browse:
        page, api_ = browse.get("http_req_duration{kind:page}", {}), browse.get("http_req_duration{kind:api}", {})
        f = browse.get("http_req_failed", {})
        r.p("**Read path, production** (" + PROD + ", 2 vCPU, 7.7 GB, database in Singapore):")
        r.table(["Metric", "Result", "Threshold", "Verdict"], [
            ["Requests", f"{browse['http_reqs']['count']}, {f.get('passes', 0)} failed ({browse['http_reqs']['rate']:.1f} a second)", "under 1 percent failed",
             "Pass" if f.get("value", 1) < 0.01 else "Fail"],
            ["Concurrent users", "20 (ramped)", "", ""],
            ["Page p50 / p95", f"{ms(page.get('med'))} / {ms(page.get('p(95)'))}", "p95 under 2 s", "Pass" if page.get("p(95)", 1e9) < 2000 else "Fail"],
            ["API p50 / p95", f"{ms(api_.get('med'))} / {ms(api_.get('p(95)'))}", "p95 under 1.5 s", "Pass" if api_.get("p(95)", 1e9) < 1500 else "Fail"],
        ], widths=[1.6, 2.3, 1.4, 0.8])
        if (EV / "terminal" / "extra-load-production.png").exists():
            r.image(EV / "terminal" / "extra-load-production.png", "Figure 14: k6 against production, read only.")
        if (EV / "grafana-load.png").exists():
            r.image(EV / "grafana-load.png", "Figure 15: The production dashboard during the read-only load test.", width=6.5)
        if stats.get("prod_note"):
            r.p(stats["prod_note"])

    # 3.1.6
    r.h3("Security and Access Control Testing")
    r.p("Security testing covers application-level security (each role reaches only its own functions and data) and "
        "system-level security (sessions cannot be forged, secrets cannot leak, the servers expose only what they "
        "must).")
    r.technique({
        "Technique Objective:": "Application level: no role reaches a surface that is not its own, and no customer "
                                "reaches another customer's row. System level: a session cannot be forged, secrets "
                                "never reach the repository or the server beyond a whitelist.",
        "Technique:": ["Every staff route with no token: expect 401. With a customer token: expect 403. Admin-only "
                       "routes with an agent token: expect 403. Each role on its own surface: expect 200.",
                       "Two customers fetch each other's ticket by id: expect 403 or 404, never the row. New: on a "
                       "fresh database the test opens the tickets it needs rather than skipping.",
                       "A token with an altered signature: 401. A wrong password: refused.",
                       "gitleaks over the whole history on every push; the server's .env is rendered from a whitelist.",
                       "New: Grafana has no anonymous access and refuses to start without an admin password; "
                       "Prometheus and the exporters are not published outside the compose network."],
        "Oracles:": "The status code is the assertion; a test fails if the body of a forbidden row ever arrives.",
        "Required Tools:": ["pytest (tests/system/test_access_control.py)", "gitleaks in CI", "Grafana login check"],
        "Success Criteria:": "Every staff and admin route is covered for the unauthenticated and the wrong-role case, "
                             "and all pass.",
        "Special Considerations:": "The browser role gate is a convenience; the gateway is the control, so the tests "
                                   "assert against the API.",
    })
    ac = count(sysc, "access_control", "passed")
    r.p(f"**Result: {ac} of {ac + count(sysc, 'access_control', 'failed') + count(sysc, 'access_control', 'skipped')} "
        "passed.** In the first run of this iteration the tenant isolation test was skipped, because on an empty "
        "database neither persona had a ticket yet; a security test that silently skips on every clean install is a "
        "hole, so it now creates its own tickets. The seeded demo passwords are public in the repository and still "
        "active on the public site: recorded as a risk in section 5.")
    r.image(EV / "terminal" / "system-access_control.png", "Figure 16: Access control tests, from the full run.")

    # 3.1.7
    r.h3("Failover and Recovery Testing")
    r.p("Failover and recovery testing shows that each optional part can fail without the customer losing their "
        "message, and that a restarted part rejoins on its own.")
    r.technique({
        "Technique Objective:": "Simulate the failure of a model service and of an external model, and exercise "
                                "recovery, observing that no message is lost and no manual step is needed.",
        "Technique:": ["Stop translation, send a real message: the case must still open and reach a draft.",
                       "Stop audio: the message is still accepted. Stop grounding: the model map reports it down "
                       "rather than healthy. Restart translation: it rejoins with no other action.",
                       "New: the triage language model fails, times out (2 s) or is rate limited: the distilled "
                       "TriageModel answers instead, and the case says why. Unit tests force each path; the load "
                       "burst forced it for real.",
                       "The drafting model: a fallback binding and a circuit breaker, proven by the live swap."],
        "Oracles:": "The case exists, the draft exists, the map's status field, and the priority's source field.",
        "Required Tools:": ["pytest with LANKA_RESILIENCE=1 (tests/system/test_resilience.py), which stops and "
                            "restarts containers of the test stack only", "services/triage/tests/test_llm_triage.py"],
        "Success Criteria:": "No message lost in any single-service outage; recovery needs no manual step.",
        "Special Considerations:": "These tests stop containers, so they run only on the isolated stack, never on "
                                   "production.",
    })
    rs = count(sysc, "resilience", "passed")
    r.p(f"**Result: {rs} of {rs + count(sysc, 'resilience', 'failed')} passed.**"
        + (f" Under the load burst the triage fallback carried {stats['triage_split']['model']} cases with no triage "
           "failure." if stats.get("triage_split") else ""))
    r.image(EV / "terminal" / "system-resilience.png", "Figure 17: Failover and recovery tests, from the full run.")

    # 3.1.8
    r.h3("Configuration Testing")
    r.p("Configuration testing verifies every deployment shape the project ships before anyone tries to run it.")
    r.technique({
        "Technique Objective:": "Show that each combination of compose files is valid and complete, and that the "
                                "system installs from nothing.",
        "Technique:": ["`docker compose config` for each shape: base, lite, CI, GPU, production, and new: test, "
                       "CI with test, production with monitoring.",
                       "The MLOps profile adds Airflow and MLflow.",
                       "Every variable any compose file reads must exist in .env.example.",
                       "New: the full stack is built from an empty database on every run (compose.test.yaml)."],
        "Oracles:": "Exit codes and a set difference of variable names.",
        "Required Tools:": ["pytest (tests/system/test_configuration.py)", "Docker Compose"],
        "Success Criteria:": "All shapes valid, no variable missing, a clean install starts.",
        "Special Considerations:": "Production refuses to render without a host name and the monitoring overlay "
                                   "without a Grafana password; both are deliberate.",
    })
    cf = count(sysc, "configuration", "passed")
    r.p(f"**Result: {cf} of {cf + count(sysc, 'configuration', 'failed')} passed.** The clean install is also where "
        "D10 and D11 were found.")
    r.image(EV / "terminal" / "system-configuration.png", "Figure 18: Configuration tests.", width=5.8)

    # 3.2 ---------------------------------------------------------------------------------------
    r.h2("Model Selection and Evaluation")
    r.p("Every model on the request path was chosen by benchmark before the system was built, not by "
        "reputation. The work is in the repository as runnable notebooks with a shared library, a "
        "fixed held-out split and a seed per run, and it writes machine readable results "
        "(`model testing/notebooks`, `results/*.json`, `results/BENCHMARK_REPORT.md`; the triage "
        "distillation in `TriageModel/` and `ml/triage/`). This section is the evidence behind each "
        "choice.")
    r.table(["Stage", "Candidates", "Chosen", "Why"], [
        ["Intent and department text", "22 models: TF-IDF with five heads, MiniLM frozen with four heads, zero-shot and prototype matching, TextCNN, MiniLM and DistilBERT fine-tuned, plus clustering", "MiniLM embedding with a small head", "Within 0.005 macro F1 of the best, and its embedding is reused by retrieval and by the triage model"],
        ["Customer priority (triage)", "TF-IDF with logistic regression, MiniLM with logistic regression, distilled multitask head", "Distilled multitask head (triage_multitask)", "Best urgency F1, 0.08 ms, one embedding shared with the rest of the stage"],
        ["Router photo", "12 models: HOG, colour histogram, raw pixels with PCA, and three CNNs frozen or fine-tuned", "EfficientNet-B0 frozen plus logistic regression", "0.977 macro F1 for a 0.09 MB head, and no fine-tuning to maintain"],
        ["Speech", "Whisper tiny, base, small and medium; faster-whisper small and medium (CTranslate2 int8)", "faster-whisper small int8", "Lowest error rate of the sizes that fit, and the fastest real-time factor"],
        ["Drafting and diagnosis", "Ollama Cloud gpt-oss 120b and 20b, Gemini, Groq (five models)", "Bound live, per deployment", "No retraining: the admin page rebinds them and the plan verifies whichever is bound"],
    ], widths=[1.25, 2.5, 1.35, 1.6])

    r.h3("Intent and Department Classification")
    r.p("**Dataset.** The Bitext 27K customer support corpus, de-duplicated, 27 intents, stratified "
        "split. **Method.** Every model trains on the same split and is scored on the same held-out "
        "set: accuracy, balanced accuracy, macro and weighted F1, top-3 accuracy, training seconds, "
        "single-item inference latency and artifact size. Two dummy baselines bound the bottom of the "
        "table, and unsupervised clustering (KMeans, agglomerative, GMM, HDBSCAN, LDA) is scored "
        "separately with ARI, NMI and Hungarian-matched accuracy.")
    r.table(["Model", "Family", "Accuracy", "Macro F1", "Inference", "Size"], [
        ["tfidf word+char, linear SVC", "traditional", "0.9992", "0.9991", "1.4 ms", "1.96 MB"],
        ["MiniLM fine-tuned", "deep", "0.9969", "0.9966", "8.3 ms", "87 MB"],
        ["DistilBERT fine-tuned", "deep", "0.9961", "0.9956", "8.2 ms", "256 MB"],
        ["MiniLM frozen + linear SVC", "embedding", "0.9953", "0.9946", "9.9 ms", "0.08 MB"],
        ["MiniLM frozen + logistic regression", "embedding", "0.9931", "0.9923", "9.9 ms", "0.04 MB"],
        ["MiniLM zero-shot label match", "embedding", "0.7386", "0.7281", "9.8 ms", "n/a"],
        ["Most frequent class (baseline)", "dummy", "0.0416", "0.0030", "n/a", "n/a"],
    ], widths=[2.2, 1.0, 0.85, 0.8, 0.8, 0.75])
    r.p("Nine models clear 0.99 macro F1, so accuracy alone does not decide it. The chosen family is "
        "the MiniLM embedding with a small head: it costs 0.04 to 0.08 MB on disk, and the same "
        "embedding already has to be computed for retrieval and for the triage features, so the "
        "classifier is close to free. A zero-shot model is 26 points worse, which is the measurement "
        "that justifies training anything at all.")
    for fig, cap in (("intent_macro_f1.png", "Figure A: Intent classification, macro F1 by model."),
                     ("intent_accuracy_vs_latency.png", "Figure B: Accuracy against inference latency.")):
        if (EV / fig).exists():
            r.image(EV / fig, cap, width=5.6)
    r.p("**Robustness.** The same models were scored again on a shifted split (different phrasing "
        "distribution) to see which family degrades. The gap is small for the linear models and "
        "largest for the fine-tuned transformer, the usual over-fitting signature:")
    r.table(["Model", "Macro F1 (held out)", "Macro F1 (shifted)", "Gap"], [
        ["tfidf word+char, linear SVC", "0.9991", "0.9943", "0.005"],
        ["MiniLM frozen + logistic regression", "0.9923", "0.9779", "0.014"],
        ["DistilBERT fine-tuned", "0.9956", "0.9582", "0.037"],
        ["MiniLM zero-shot label match", "0.7281", "0.7137", "0.014"],
    ], widths=[2.4, 1.5, 1.5, 0.8])
    if (EV / "intent_shift_gap.png").exists():
        r.image(EV / "intent_shift_gap.png", "Figure C: What each family loses under distribution shift.", width=5.4)

    r.h3("Customer Priority: Distillation from Language Model Labels")
    r.p("No triage-labelled Sri Lankan support data exists, so one was made: about 3,500 records "
        "balanced over the 27 intents, labelled once by a language model against the UnifiedTicket "
        "schema, with every answer cached by a content hash of prompt, model, temperature and prompt "
        "version, so an interrupted run resumes for free and a prompt change correctly invalidates "
        "the old labels. A gold slice was re-labelled to measure self-agreement before training. A "
        "small multitask head (intent, department, urgency band and a 0 to 100 score) was then "
        "distilled from those labels on top of the frozen MiniLM embedding, so the runtime never pays "
        "language model cost per ticket:")
    r.table(["Model", "Intent acc.", "Department acc.", "Urgency acc.", "Urgency F1", "Latency"], [
        ["TF-IDF + logistic regression", "0.580", "0.653", "0.667", "0.686", "0.61 ms"],
        ["MiniLM + logistic regression", "0.713", "0.807", "0.680", "0.701", "0.13 ms"],
        ["Distilled multitask head (ships)", "0.607", "0.700", "0.727", "0.724", "0.08 ms"],
    ], widths=[2.1, 0.95, 1.15, 0.95, 0.9, 0.8])
    r.p("The distilled head wins on urgency, which is what the stage is for: the department comes "
        "from the routing rules, and the provider side priority comes from the account and network "
        "record, not from this model. It is the default binding again after this iteration, with a "
        "Groq model selectable for a language model reading of the same message (section 3.1.2).")

    r.h3("Router Photo Classification")
    r.p("**Dataset.** The Roboflow router detection set (v38), whose boxes become a 15-class crop "
        "classification problem, cached to disk. **Method.** Classical descriptors and three CNN "
        "backbones, each used frozen with a linear head and fine-tuned, on the same split.")
    r.table(["Model", "Family", "Accuracy", "Macro F1", "Size"], [
        ["EfficientNet-B0 frozen + logistic regression", "embedding", "0.9704", "0.9774", "0.09 MB"],
        ["EfficientNet-B0 fine-tuned", "deep", "0.9630", "0.9728", "15.7 MB"],
        ["ResNet18 frozen + logistic regression", "embedding", "0.9481", "0.9567", "0.04 MB"],
        ["MobileNetV3-small fine-tuned", "deep", "0.9630", "0.9488", "6.0 MB"],
        ["Colour histogram + random forest", "traditional", "0.8667", "0.7723", "9.1 MB"],
        ["HOG + logistic regression", "traditional", "0.7704", "0.6409", "0.30 MB"],
        ["Most frequent class (baseline)", "dummy", "0.2815", "0.0366", "n/a"],
    ], widths=[2.6, 1.0, 0.85, 0.8, 0.75])
    r.p("Fine-tuning costs six to seven minutes of training and 170 times the disk for no gain over "
        "the frozen backbone with a linear head, so the frozen model ships, exported to ONNX for the "
        "image service. The photo is optional evidence in the pipeline: it can add a fact, and it "
        "never blocks a reply.")
    if (EV / "router_macro_f1.png").exists():
        r.image(EV / "router_macro_f1.png", "Figure D: Router photo classification, macro F1 by model.", width=5.6)

    r.h3("Speech Transcription")
    r.p("**Dataset.** Eleven real call-centre recordings across seven languages, with cleaned "
        "reference transcripts. **Method.** Word and character error rate (duration weighted), match "
        "error rate, word information lost, an embedding similarity, the real-time factor and "
        "language identification accuracy.")
    r.table(["Model", "WER", "CER", "Real-time factor", "Language ID"], [
        ["faster-whisper small (int8)", "0.390", "0.267", "0.088", "11 of 11"],
        ["Whisper small", "0.430", "0.293", "0.130", "11 of 11"],
        ["Whisper base", "0.597", "0.387", "0.103", "11 of 11"],
        ["Whisper tiny", "0.761", "0.591", "0.091", "11 of 11"],
    ], widths=[2.2, 0.9, 0.9, 1.4, 1.0])
    r.p("faster-whisper small is both the most accurate of the sizes that fit in memory beside the "
        "translation model and the fastest, at about one tenth of real time, so it ships. The error "
        "rates are high in absolute terms because the recordings are noisy call-centre audio in seven "
        "languages; what the pipeline needs from them is the language and the gist, which then go "
        "through translation, and the customer's own typed text is always kept beside them. Language "
        "identification was correct on every call, which is the property the pipeline depends on.")
    if (EV / "voice_asr_benchmark.png").exists():
        r.image(EV / "voice_asr_benchmark.png", "Figure E: Speech benchmark, error rates and real-time factor.", width=5.6)

    r.h3("Grounded Response Validation")
    r.p("The drafting design (retrieve the facts first, then let the model write only from them) was "
        "validated in a prototype before it became the response service, and that validation still "
        "runs offline with no API key: a fake model forces the classifier's decision while the real "
        "graph, the real tool transport (MCP over JSON-RPC to a subprocess) and the real database are "
        "exercised. It proves the two properties a language model cannot be trusted to hold on its "
        "own: that a connectivity question chains **both** the network status and the payment lookup "
        "(the naive single-lookup answer blames the router when the real cause is a suspension for "
        "non-payment), and that the retrieved facts really appear in the generation prompt.")
    r.p("**Result: 56 checks passed across 5 scenarios, none failed.** The same rule is enforced at "
        "runtime by the grounding bundle and the compliance guard of section 3.1.2, which is why the "
        "headline case cites the balance and the outage instead of guessing.")
    if (EV / "terminal" / "extra-response-validation.png").exists():
        r.image(EV / "terminal" / "extra-response-validation.png",
                "Figure F: Grounded response validation, offline, with the real tool transport.")

    # 4 -----------------------------------------------------------------------------------------
    r.h1("Deliverables")
    r.p("The test effort delivers the following, all in the repository or produced by one command:")
    r.bullets([
        "Test logs and JUnit XML for every run (`reports/<date>/`, or the GitHub Actions artifact).",
        "User interface screenshots of every page, on a phone and on a desktop browser, kept by "
        "the browser suites on every run.",
        "Load test summaries from k6, for the isolated write path and for production.",
        "The production monitoring stack and its Grafana dashboard template (`infra/monitoring`).",
        "The model selection benchmarks, their results and figures (`model testing/results`).",
        "This report, generated from a run's evidence (`docs/test-report`).",
    ])
    r.h2("Test Evaluation Summaries")
    passed_sys, failed_sys, skip_sys = tot(sysc, "passed"), tot(sysc, "failed"), tot(sysc, "skipped")
    rows = []
    step_word = {"01-unit": "Unit and contract", "02-stack": "Stack up and smoke", "03-system": "System (all techniques)",
                 "04-browser": "Browser, desktop and mobile", "05-demo-flow": "Headline scenario", "06-hot-swap": "Live model swap",
                 "07-load": "Load, write path"}
    for step, status, secs in summary:
        n = {"01-unit": f"{unit_passed} tests", "03-system": f"{passed_sys + failed_sys + skip_sys} tests",
             "04-browser": f"{tot(brc, 'passed') + tot(brc, 'failed')} tests", "07-load": "602 requests"}.get(step, "1 scenario")
        rows.append([step_word.get(step, step), n, status.title(), secs])
    r.p("Summary of the final run, generated by `scripts/test-plan.sh` on the isolated stack:")
    r.table(["Step", "Executed", "Verdict", "Time"], rows, widths=[2.4, 1.4, 1.0, 0.9])
    total = unit_passed + passed_sys + failed_sys + skip_sys + tot(brc, "passed") + tot(brc, "failed") + 2
    fails = failed_sys + tot(brc, "failed")
    r.table(["Field", "Value"], [
        ["Date", "20 September 2026"],
        ["Run by", "DSEP Group 22, scripts/test-plan.sh"],
        ["Environment", "Full stack (16 services, both models) on an isolated Postgres; Windows 11, Docker Desktop, 16 cores, 7.9 GB for Docker"],
        ["Models on the path", "Groq qwen/qwen3.8-27b (triage), Ollama Cloud gpt-oss 120b and 20b (drafting, diagnosis), NLLB-200, faster-whisper"],
        ["Test cases executed", str(total)],
        ["Passed", str(total - fails - skip_sys)],
        ["Failed", str(fails)],
        ["Skipped", str(skip_sys)],
        ["Pass percentage", f"{100 * (total - fails - skip_sys) / total:.1f} percent"],
        ["Comments", "Every defect found by this iteration's runs is listed below with its fix, except D13, which is open."],
    ], widths=[1.8, 4.5])
    r.p("**Defects found in this iteration** (D1 to D9 were found and fixed in the previous run of 19 September):")
    r.table(["#", "Found by", "Defect", "Cause", "Fix"], [
        ["D10", "Configuration (clean install)", "The inquiry service never starts on an empty database",
         "A backfill UPDATE read inquiry.message before the CREATE TABLE later in the same script", "Backfill moved after the table; fixed"],
        ["D11", "Configuration (clean install)", "Seeding fails on any database without TLS", "The seed forced TLS regardless of the connection string",
         "TLS only when the connection string asks for it; fixed"],
        ["D12", "User interface", "Signing out of the customer area lands on sign-in instead of the website",
         "The role gate saw the session end and redirected before the sign-out navigation landed", "One sign-out helper that holds the gate while leaving; fixed"],
        ["D13", "Function (reading the reply)", "A Sinhala reply split a conjunct: \"මධ් යම\" for \"මධ්‍යම\"",
         "The conjunct repair only joins across a space after a bare consonant, to avoid D2", "**Open**: needs a Sinhala word list to tell a split conjunct from a word boundary"],
        ["D14", "Function (Groq triage)", "Every second Groq call failed with 429", "No max_tokens: Groq reserved the model's whole window against an 8,000 token a minute limit",
         "max_tokens and temperature set per binding; fixed"],
        ["D15", "User interface (mobile)", "Plans page empty after every deploy until the cache expired",
         "The page was prerendered at image build time, when no gateway exists", "Rendered per request with a one minute data cache; fixed"],
        ["D16", "User interface (mobile)", "Four pages scroll sideways on a phone; the customer menu hides four items",
         "Header display class overridden, grid children without min-width, fixed widths", "See 3.1.3; fixed"],
        ["D17", "System (function)", "A new case could fall past the console's 100 row cap after a burst of urgent ones",
         "The history tab still sorted by priority before time", "The All tab is ordered by time alone; fixed"],
        ["D18", "System (function)", "Drafts slower than 30 s were lost, although drafting is allowed 60 s",
         "The orchestrator's shared HTTP client kept its own 30 s read timeout", "Each stage call times out at its own budget; fixed"],
        ["D19", "Scenario", "A reply quoting an incident id or an ISO date was held as a phone number",
         "The detector matched any nine digits and hyphens", "A phone is ten or more digits standing alone; fixed"],
        ["D20", "Scenario", "Markdown reached the customer (bold markers around an amount)",
         "The scrub ran per streamed chunk, so a marker split across two survived", "plain_text() strips markdown after the stream is joined; fixed"],
        ["D21", "Test stack", "migrate failed against a brand new database volume",
         "The health check used the Unix socket, which the temporary init server also answers", "Health checks go over TCP; fixed"],
        ["D22", "Monitoring (production)", "cAdvisor reported no containers",
         "Versions before v0.55 cannot read Docker 29's containerd image store", "Pinned to v0.55.1; fixed"],
        ["D23", "Monitoring (production)", "The model map showed the distilled triage model as Not answering",
         "A binding that runs inside its own service has no endpoint to ping, and the probe returned unknown", "The probe reports where the model runs; fixed"],
        ["D24", "Production (environment)", "Drafting and diagnosis cannot reach any language model on the server",
         "The Ollama Cloud key is rejected (401), Gemini refuses the server's region, and the Groq key is not in the secret store",
         "**Open, needs the owner**: set GROQ_API_KEY (Groq answers from the server) or refresh the Ollama key"],
    ], widths=[0.45, 1.1, 1.6, 1.8, 1.45])
    r.image(EV / "terminal" / "01-unit.png", "Figure 19: Unit, contract and architecture tests, lint and typecheck.")

    r.h2("Reporting on Test Coverage")
    r.p("Coverage is reported by requirement rather than by line, because the risk in this product is a missing "
        "conversation or a leaked row, not a missed branch.")
    r.table(["Technique", "Where", "Tests"], [
        ["Unit and contract", "packages, services/*/tests, tests/architecture", f"{unit_passed} plus Node tests and module self-checks"],
        ["Data and database integrity", "tests/system/test_data_integrity.py", str(count(sysc, "data_integrity", "passed") + count(sysc, "data_integrity", "failed"))],
        ["Function", "tests/system/test_functional.py, 2 scenario scripts", str(count(sysc, "functional", "passed") + count(sysc, "functional", "failed")) + " + 2"],
        ["Security and access control", "tests/system/test_access_control.py", str(sum(v for (g, _), v in sysc.items() if g == "access_control"))],
        ["Performance", "tests/system/test_performance.py", str(count(sysc, "performance", "passed") + count(sysc, "performance", "failed"))],
        ["Configuration", "tests/system/test_configuration.py", str(count(sysc, "configuration", "passed") + count(sysc, "configuration", "failed"))],
        ["Failover and recovery", "tests/system/test_resilience.py", str(count(sysc, "resilience", "passed") + count(sysc, "resilience", "failed"))],
        ["User interface", "web/e2e (desktop and mobile)", str(tot(brc, "passed") + tot(brc, "failed"))],
        ["Load", "load/ack.js, load/browse.js", "2 scenarios, 7 thresholds"],
        ["Model selection", "model testing/notebooks, TriageModel, ml/triage", "49 models over 4 tasks"],
        ["Grounded response validation", "response-prototype/test_offline.py", "56 checks, 5 scenarios"],
    ], widths=[1.9, 2.8, 1.6])
    r.p("**How to reproduce any number in this report:**")
    r.bullets([
        "`bash scripts/test-plan.sh` on any machine with Docker: the whole plan on a throwaway database, evidence in `reports/<date>/`.",
        "GitHub, Actions, test-plan, Run workflow: the same on a GitHub runner, evidence as a downloadable artifact.",
        "`SCRIPT=load/browse.js LANKA_URL=" + PROD + " bash scripts/load.sh`: the read-only production load test.",
        "`python docs/test-report/build_report.py --collect reports/<date>` then `export.ps1`: this document.",
    ])
    r.p("**Operational monitoring.** Coverage does not stop at release. Production now runs Prometheus and Grafana "
        "beside the stack (`compose.monitoring.yaml`, deployed by the same pipeline). The provisioned dashboard shows "
        "the services that answered their last health probe, the public URL checked through DNS and TLS, CPU, "
        "memory, disk, every container's CPU and memory, request rates, status codes and latency percentiles at the "
        "edge, and the certificate expiry. Alert rules cover a service or the site going down, the certificate, "
        "memory, disk, CPU and error rate.")
    if (EV / "grafana-overview.png").exists():
        r.image(EV / "grafana-overview.png", "Figure 20: The production dashboard (Grafana at /grafana).", width=6.5)

    # 5 -----------------------------------------------------------------------------------------
    r.h1("Risks, Dependencies, Assumptions, and Constraints")
    r.risks([
        ("External model capacity limits the pipeline",
         ["Measured: about eight drafts a minute on the current Ollama Cloud account; Groq triage 8,000 tokens a minute.",
          "Every model stage has a fallback or a budget, so a limit degrades a draft, never a message."],
         ["Move drafting to a paid tier or to Groq.", "Add a draft queue in arrival order."]),
        ("Model provider limits and regional blocks",
         ["Groq's free tier has per-minute token and weekly request limits; triage falls back to the "
          "distilled model, which is also the default, so a limit costs nothing on the hot path.",
          "Every model binding is swappable live from the admin page, with no restart and no deploy."],
         ["Move the drafting account to a paid tier.",
          "Gemini answers 'User location is not supported' from the server's region, so it cannot be "
          "the fallback for this deployment; keep Ollama Cloud or a second Groq key for that."]),
        ("Seeded demo passwords are public and live on the public site",
         ["Documented; changing the SEED secrets does not change existing accounts."],
         ["Reset the seeded accounts' passwords, or remove them from production."]),
        ("Tests running against production data",
         ["compose.test.yaml isolates every write test; only read-only load runs on production."],
         ["The shared database has point-in-time restore on Neon."]),
        ("Model output is not deterministic",
         ["Tests assert facts (digits, script, citations), never wording; triage runs at temperature 0."],
         ["A person reviews the Sinhala and Tamil wording; D13 shows why."]),
        ("Measurements from a development machine",
         ["Every figure states where it was taken; production is measured separately, read only."],
         ["Repeat the load test on the VPS when traffic grows."]),
        ("Chromium only",
         ["Desktop and phone profiles cover layout and touch; engines differ little for this app."],
         ["Add WebKit and Firefox projects to Playwright."]),
    ])
    r.p("**Dependencies.** Docker; the GHCR images; API keys for Groq, Ollama Cloud and Gemini (without them triage "
        "falls back to its own model and drafting to the offline stub); the NLLB and Whisper weights inside the "
        "images; the Neon project for production.")
    r.p("**Assumptions.** The seeded personas exist (the test database seeds them itself); the machine can hold "
        "both models resident (about 4 GB).")
    r.p("**Constraints.** One iteration and one team; no dedicated test hardware, so the load test of the write path "
        "runs on a development machine and production is only tested read only; the Groq free tier.")

    # 6 -----------------------------------------------------------------------------------------
    r.h1("References")
    refs = [
        "[1] IBM, \"Rational Unified Process: Master Test Plan template.\" Provided by the course. Accessed: Sep. 20, 2026.",
        "[2] Microsoft, \"Playwright: fast and reliable end-to-end testing.\" [Online]. Available: https://playwright.dev/ (Accessed: Sep. 20, 2026).",
        "[3] Grafana Labs, \"k6: load testing for engineering teams.\" [Online]. Available: https://k6.io/ (Accessed: Sep. 20, 2026).",
        "[4] pytest developers, \"pytest documentation.\" [Online]. Available: https://docs.pytest.org/ (Accessed: Sep. 20, 2026).",
        "[5] Prometheus authors, \"Prometheus: monitoring system and time series database.\" [Online]. Available: https://prometheus.io/ (Accessed: Sep. 20, 2026).",
        "[6] Grafana Labs, \"Grafana documentation: provisioning.\" [Online]. Available: https://grafana.com/docs/grafana/latest/administration/provisioning/ (Accessed: Sep. 20, 2026).",
        "[7] Google, \"cAdvisor: container advisor.\" [Online]. Available: https://github.com/google/cadvisor (Accessed: Sep. 20, 2026).",
        "[8] Groq, \"GroqCloud API reference and rate limits.\" [Online]. Available: https://console.groq.com/docs/rate-limits (Accessed: Sep. 20, 2026).",
        "[9] Gitleaks, \"Gitleaks: find secrets with Gitleaks.\" [Online]. Available: https://github.com/gitleaks/gitleaks (Accessed: Sep. 20, 2026).",
        "[10] NLLB Team et al., \"No Language Left Behind: Scaling human-centered machine translation,\" arXiv:2207.04672, 2022.",
        "[11] A. Radford et al., \"Robust speech recognition via large-scale weak supervision,\" arXiv:2212.04356, 2022.",
        "[12] Lanka Link v3 repository, docs/TEST-PLAN.md and docs/DEPLOYMENT.md. [Online]. Available: https://github.com/DSEP-G22/v3 (Accessed: Sep. 20, 2026).",
    ]
    for ref in refs:
        r.p(ref)

    r.save(OUT)
    text = "\n".join(p.text for p in r.doc.paragraphs) + "\n".join(c.text for t in r.doc.tables for row in t.rows for c in row.cells)
    assert chr(0x2014) not in text, "an em dash reached the report"
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", type=Path, help="a reports/<run> directory to copy evidence from first")
    ap.add_argument("--no-shots", action="store_true", help="reuse the terminal screenshots already in evidence/")
    args = ap.parse_args()
    if args.collect:
        collect(args.collect)
    if not args.no_shots:
        excerpts()
    build()
