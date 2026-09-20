# The written test report

`Lanka-Link-v3-Master-Test-Plan.docx` (and `DSEP22 Test Report.pdf`, the same document exported)
is the RUP master test plan and test report for Lanka Link v3: the plan, the techniques, the
results of the run of 20 September 2026, the model selection benchmarks, the defects and the
risks, with the logs and the screenshots that back every number.

## Where the numbers come from

`evidence/` holds exactly what the report quotes, so each figure can be checked:

| Path | What it is |
| --- | --- |
| `logs/` | One log per step of `bash scripts/test-plan.sh`, as the report prints them |
| `terminal-src/` | The same logs, plus the per technique slices of the system log |
| `junit-system.xml`, `junit-browser.xml` | Machine readable results for every test case |
| `load-ack.json`, `load-browse.json` | k6 summaries: the write path, and the read-only run on production |
| `pipeline.json` | Per stage timings and the triage split, queried from the test database after the load step |
| `mobile/`, `desktop/` | Every page photographed by the browser suites, phone and desktop |
| `grafana-*.png` | The production dashboard |
| `intent_*.png`, `router_*.png`, `voice_*.png` | Figures from the model selection benchmarks (`model testing/results`) |
| `mobile-before-sheet.png` | The same phone pages on the build that preceded this iteration |
| `extra-*.log` | The production load test and the grounded response validation |

## Producing a new one

Run the plan, which refreshes everything under `reports/<date>/`:

```bash
bash scripts/test-plan.sh
```

Then copy that run's logs, JUnit XML, k6 summaries and screenshots into `evidence/` and update the
document. `template.docx` is the RUP template the course supplied, unmodified, and the document
keeps its styles, header, footer and table of contents; in Word, select all and press F9 to
rebuild the contents table after editing.
