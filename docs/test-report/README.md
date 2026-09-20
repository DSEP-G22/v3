# The written test report

`Lanka-Link-v3-Master-Test-Plan.docx` (and the exported PDF) is the RUP master test plan and test
report for Lanka Link v3: the plan, the techniques, the results of the run, the model selection
benchmarks, the defects and the risks, with screenshots.

It is **generated**, not hand written, so a new test run produces a report that matches it.

```bash
bash scripts/test-plan.sh                                   # 1. run the plan, evidence in reports/<date>/
uv run --with python-docx --with pillow \
  python docs/test-report/build_report.py --collect reports/<date>   # 2. build the .docx
powershell -File docs/test-report/export.ps1 \
  docs/test-report/Lanka-Link-v3-Master-Test-Plan.docx      # 3. fill the contents table, write the PDF
```

| File | What it is |
| --- | --- |
| `build_report.py` | The report: prose here, every count and timing read from the evidence |
| `docxkit.py` | Writes into `template.docx` with the template's own styles, tables, header and footer |
| `template.docx` | The RUP master test plan template the course supplied, unmodified |
| `export.ps1` | Word updates the table of contents and the fields, then saves a PDF (Windows) |
| `evidence/` | What the report quotes: logs, JUnit XML, k6 summaries, screenshots, `pipeline.json` |

`--collect` copies a run's evidence in (and shrinks the phone screenshots). `--no-shots` reuses the
terminal screenshots already in `evidence/terminal` instead of rendering them again.

Evidence that does not come from `scripts/test-plan.sh`:

- `extra-load-production.log`, `load-browse.json`: the read-only load test against production.
- `grafana-*.png`: the production dashboard (`web/scripts/grafana-shot.mjs`).
- `extra-response-validation.log`: `python test_offline.py` in `response-prototype/`.
- `intent_*.png`, `router_*.png`, `voice_*.png`: figures from `model testing/results/`.
- `mobile-before-sheet.png`: the phone screenshots taken before the mobile work, for comparison.
- `pipeline.json`: the per stage timings and the triage split, queried from the test database after
  the load step (the SQL is quoted in `docs/TEST-RESULTS.md`).
