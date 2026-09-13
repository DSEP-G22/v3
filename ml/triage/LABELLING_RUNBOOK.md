# Dataset generation + labelling runbook

**Audience: the model or engineer executing this.** Every command, file and threshold is
written out. Do not improvise, do not substitute a different corpus, and do not skip a gate
because the previous step "looked fine". Where a step says STOP, stop.

The chain you are running:

```
Bitext CSV  ─┐
router COCO ─┼─→ extract/ + compose.py ─→ data/unlabelled.jsonl  (triage = null)
synthetic   ─┤                                     │
ASR cache   ─┘                                     ▼
                                     label/run_labelling.py  (Ollama teacher)
                                                   │
                                                   ▼
                          data/labelled.jsonl → validate.py → make_gold.py
                                                   │              │
                                                   ▼              ▼
                                            data/train.jsonl   data/gold.jsonl
                                                   │
                                                   ▼
                                        train/train_triage.py → artifacts/
```

---

## 0. Read this first

### What already exists

All the code exists and runs: `extract/`, `label/`, `train/`. You are not writing a pipeline
from scratch. You are fixing a corpus and running a teacher over it.

### What is broken

`data/labelled.jsonl` was produced by the **offline heuristic stand-in**, not by a language
model. Every one of its 3511 rows carries
`metadata.labelled_by = "heuristic:heuristic/static-equation-v1"`. The result:

| urgency | count | share |
|---|---|---|
| low | 3456 | 98.4% |
| normal | 55 | 1.6% |
| high | 0 | 0% |
| critical | 0 | 0% |

`artifacts/score_table.json` reports `acc_urgency = 0.9333`. That number is a model that
learned to answer `low` every time. `gold.jsonl` and `train.jsonl` are carved from the same
labels, so all three files are worthless.

There are **two** causes, and fixing only one leaves you where you started:

1. **No teacher was ever run.** The heuristic provider answers with the static keyword
   equation, so a student distilled from it recovers the keyword rules and nothing else , 
   exactly the failure the LLM pass exists to prevent.
2. **The corpus cannot produce `high`/`critical` even with a perfect teacher.** Bitext is an
   *e-commerce* support taxonomy ,  orders, refunds, invoices, newsletter subscriptions. It
   contains no outage, no line fault, no dead service, no safety hazard. The router COCO
   corpus labels *components* (`power`, `power-conn`, `fiber-conn`, `lan-cable`, `usb`, …)
   and carries **no LED state**, so `Signals.fault_leds` is empty on every record and an
   attached photograph contributes `device_visible=true` and a component list, nothing more.
   Nothing in the corpus is escalatable, so no teacher can escalate it.

Section 2 fixes cause 2. Sections 3 to 5 fix cause 1.

### Hard rules

- **Delete the stale label files before you start.** They will otherwise be silently reused
  by `make_gold.py` and `train_triage.py`:
  ```powershell
  Remove-Item d:\DSEP22\TriageModel\data\labelled.jsonl,
              d:\DSEP22\TriageModel\data\labelled_repeat.jsonl,
              d:\DSEP22\TriageModel\data\train.jsonl,
              d:\DSEP22\TriageModel\data\gold.jsonl -ErrorAction SilentlyContinue
  ```
- **Keep `data/label_cache.json`.** Cache keys include the model id, so the heuristic entries
  can never be served to an Ollama run. Deleting it only throws away resumability.
- **Never rename or remove a field in `schema.py`.** `MVP/api/schema.py` re-exports that
  module and `train/features.py` builds its feature matrix from `Signals.as_features()`;
  changing a name silently changes the tensor layout.
- **Never hand-write a `triage` block into the corpus.** The whole point of the pass is that
  triage labels do not exist in any source dataset. A label you wrote yourself, or a label
  copied from a scenario template, makes the dataset circular and the score meaningless.

---

## 1. Environment

### Interpreter

```powershell
$PY = "d:\DSEP22\MVP\.venv\Scripts\python.exe"
cd d:\DSEP22
& $PY -c "import pydantic, pandas; print(pydantic.VERSION, pandas.__version__)"
```

**PowerShell quoting.** PowerShell 5.1 strips double quotes when it hands an argument to a
native executable, so `& $PY -c @'... open("f") ...'@` reaches Python as `open(f)` and dies
with a `SyntaxError`. Every Python snippet below therefore uses **single quotes inside the
code**. If you need double quotes in Python, put the code in a `.py` file and run that file.

Everything below is run **from the repo root `d:\DSEP22`**, invoking scripts by path:

```powershell
& $PY TriageModel\extract\compose.py
```

Never `python -m`, never from inside `TriageModel/`. The scripts import a `_paths` /
`common` bootstrap that puts `TriageModel` on `sys.path` *before* `MVP/api`, because both
directories contain a module named `schema` ,  `MVP/api/schema.py` is a re-export shim, and
importing it first gives you two distinct class objects for the same pydantic model, after
which every cross-module `model_validate` fails with a confusing type error. If you see
`ModuleNotFoundError: No module named 'schema'`, you are in the wrong directory.

### Ollama

Ollama is the teacher. On this machine it is **not installed** (`ollama` is not on PATH and
`http://localhost:11434` does not answer). Install and start it:

```powershell
winget install Ollama.Ollama      # or download from https://ollama.com/download
ollama serve                      # leave running in its own terminal
```

Preflight ,  this must return JSON before you go further:

```powershell
Invoke-WebRequest http://localhost:11434/api/tags | Select-Object -Expand Content
```

### Which model

| Tag | Where it runs | Use when |
|---|---|---|
| `gpt-oss:120b-cloud` | Ollama's servers, no weights downloaded, needs `ollama signin` | **First choice.** A 3.5k-record pass finishes in hours, not days. |
| `gpt-oss:20b` | Local | Offline requirement, or no Ollama account. Pull with `ollama pull gpt-oss:20b`. |
| `llama3.1:8b` | Local | Weak fallback. Poorer JSON adherence and noticeably flatter urgency judgement ,  check the smoke sample in §4.1 harder. |

**Throughput arithmetic ,  do this before launching the full run.** Effective concurrency is
**2**, not whatever `--workers` says: `OllamaProvider._semaphore = threading.Semaphore(2)`
in `MVP/api/llm/ollama.py` is a class attribute shared by every instance, so extra threads
only queue.

```
wall clock ≈ records × seconds_per_call ÷ 2
3500 × 3 s  ÷ 2 ≈ 1.5 h     (cloud tag)
3500 × 60 s ÷ 2 ≈ 29 h      (20b on CPU)
```

Time one call first (§4.1 does this for you). If the local number is unacceptable, reduce the
corpus with `--limit`/`--synthetic` in §3 rather than degrading the model ,  a smaller
well-labelled corpus beats a large badly-labelled one.

### Configuration

In `MVP/.env`:

```
LLM_PROVIDER=ollama
LLM_MODEL=gpt-oss:120b-cloud
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TIMEOUT_S=300
OLLAMA_NUM_CTX=8192
```

- `OLLAMA_NUM_CTX` must stay at 8192 or higher. The prompt is a system block plus three
  few-shot pairs plus the ticket; a smaller context window truncates it **silently**, and the
  first thing lost is the labelling rubric.
- Always pass `--provider ollama` on the command line as well. With no `--provider`,
  `get_provider(None)` reads the dev panel's live selection out of the database
  (`MVP/api/llm/selection.py`), which is not what a batch job should depend on.
- `LLM_MODEL` is only honoured for the provider it was configured against
  (`provider.model_id_for`), so set `LLM_PROVIDER=ollama` too, or the id is ignored and
  `config/models.yaml`'s `llama3.1:8b` is used instead.

---

## 2. Fix the corpus before labelling

Three edits. Do all three before generating anything.

### 2.1 What you must NOT do

Do not fabricate `led_states` on the COCO evidence records. LED state is not observable in
that corpus ,  it labels connectors and cables. Inventing "POWER = red" from the presence of a
`power-conn` box would create a visual→urgency correlation that `MVP/api/pipeline/vision.py`
can never reproduce on a real ticket, so the model would learn a signal that does not exist
in production. Image evidence stays exactly as it is.

The urgency the corpus lacks has to come from **text**, and it has to be marked as synthetic.

### 2.2 New file: `TriageModel/extract/extract_synthetic.py`

A template bank of telecom support requests, slot-filled deterministically. Its vocabulary is
taken from `MVP/knowledge/sop_*.md`, so the synthetic tickets use the same terms the RAG
index and the agent SOPs already cover.

**The templates carry no triage label.** They control wording only; the teacher still decides
intent, department, urgency and score. A template that shipped its own band would make the
dataset circular.

Write the file exactly as below.

```python
"""Synthetic telecom requests, to give the corpus something escalatable.

Bitext is an e-commerce taxonomy: it has no outage, no line fault, no dead service and no
safety hazard, so a corpus built from it alone cannot produce a `high` or `critical` label no
matter how good the teacher is. This module supplies the missing half of the urgency range.

Every record is marked `metadata.source="synthetic_telecom"` with its `template_id`, so any
score can be reported per source and nobody can mistake generated text for real traffic. The
templates deliberately carry NO triage label -- they shape the wording, and the labelling pass
still assigns intent, department, urgency and priority score. A template that shipped its own
band would make the dataset circular.

Vocabulary is lifted from `MVP/knowledge/sop_*.md` so the synthetic text uses the same terms
the SOPs and the RAG index cover.

    python TriageModel/extract/extract_synthetic.py --count 700
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from dataclasses import dataclass

from common import SEED


@dataclass(frozen=True)
class SyntheticRequest:
    template_id: str
    text: str
    device_relevant: bool     # whether a photograph of the hardware would plausibly be attached


SLOTS: dict[str, tuple[str, ...]] = {
    "hours": ("since 6am", "since yesterday evening", "for the last four hours",
              "since Friday night", "for two days now", "since about 11pm",
              "since the storm on Tuesday", "since early this morning"),
    # Phrased to hit `pipeline.signals.LOCAL_TERMS` / `REGIONAL_TERMS`, so the rule prefill
    # produces a sensible `outage_scope` hint. The teacher can still override it.
    "place": ("our whole street", "our whole building", "my neighbourhood",
              "all our offices", "the whole block", "everyone in my area",
              "my neighbours and me", "the whole area"),
    "area": ("this street", "the block", "my area", "the estate", "the village"),
    "device": ("router", "modem", "ONT", "fibre box", "home hub", "wall box"),
    # Every option must read grammatically after a leading "The " -- the templates use it
    # that way, so an option like "no LEDs are lit" would produce "The no LEDs are lit".
    "led": ("power LED is solid red", "internet LED is amber and never turns green",
            "internet LED is completely off", "power LED blinks red and it keeps rebooting",
            "power LED is completely dark", "internet LED flashes and then goes out"),
    "code": ("ERR-503", "E102", "WAN-0x21", "SYNC-14", "ERR 900", "E-455"),
    "amount": ("49.90", "112.40", "27.00", "230.15", "18.75", "64.20", "89.99"),
    "days": ("three days", "a week", "ten days", "two weeks", "nearly a month"),
    "count": ("twice", "three times", "four times"),
    "nth": ("second time", "third time", "fourth time"),
    "plan": ("100 Mbps fibre plan", "500 Mbps plan", "business fibre line", "ADSL plan",
             "family broadband bundle"),
    "speed": ("3 Mbps", "just under 8 Mbps", "less than 1 Mbps", "about 12 Mbps"),
}

# Openers and closers, applied independently at random. Without them 700 records collapse
# into ~26 sentences with the nouns swapped, and the encoder would see the template rather
# than the complaint. The empty entries keep plenty of records bare.
OPENERS: tuple[str, ...] = (
    # Each ends a sentence, so the template's own capital letter still starts one.
    "", "", "", "Hello. ", "Hi there. ", "Good morning. ", "Please help. ",
    "Sorry to bother you. ", "I need some help. ", "URGENT: ",
)
CLOSERS: tuple[str, ...] = (
    "", "", "", " Please advise.", " Can someone call me back today?",
    " I would appreciate a quick reply.", " What can you do about this?",
    " Please let me know what happens next.", " Thanks.",
)

# (template_id, device_relevant, text)
#
# Coverage is deliberate: outages and hazards for the top of the band, single-line faults and
# repeat contacts for the middle, disputes and routine questions for the bottom. Do not prune
# the routine ones -- a corpus of nothing but emergencies teaches the opposite bias.
TEMPLATES: tuple[tuple[str, bool, str], ...] = (
    # --- wide-scope outages ------------------------------------------------------------ #
    ("outage_area", False,
     "There has been no internet {hours} for {place}. Nobody here can get online at all."),
    ("outage_area_business", False,
     "The line has been down for {place} {hours}. We run a business from these premises and "
     "cannot take card payments while it is out."),
    ("outage_repeat", False,
     "The connection has gone down across {place} {count} this week. It is down again now, "
     "{hours}. I have already reported it and nothing has changed."),
    ("outage_phone_and_net", False,
     "Both the internet and the phone line are dead {hours} for {place}. There is no dial "
     "tone at all."),
    # --- safety / on-site --------------------------------------------------------------- #
    ("hazard_cable", False,
     "The drop cable from the pole to my house has come down and is lying across the "
     "pavement where children walk. Service has been out {hours}."),
    ("hazard_burning", True,
     "My {device} started smelling of burning and there are scorch marks on the casing. I "
     "have unplugged it at the wall. Nothing is working now."),
    ("hazard_box_open", False,
     "The street cabinet on my corner has been left open with the cables exposed since the "
     "engineers were here. Half of {area} lost service afterwards."),
    # --- single-line hard faults --------------------------------------------------------- #
    ("dead_line", True,
     "My {device} has been dead {hours}. The {led}. I have power-cycled it twice and it "
     "makes no difference."),
    ("dead_line_repeat", True,
     "I have called {count} about this and nobody has called back. The {led} and I have had "
     "no service for {days}."),
    ("no_sync", True,
     "The {led} on my {device}. I reseated the WAN cable at both ends as your support page "
     "says and it still will not sync."),
    ("error_code", True,
     "My {device} shows {code} on the status page and there is no connection. It has been "
     "like this {hours}."),
    ("wfh_blocked", False,
     "I work from home and have had no connection {hours}. I have missed two client calls "
     "already and I have a deadline today."),
    # --- degraded but working ------------------------------------------------------------ #
    ("intermittent", True,
     "The connection keeps dropping every few minutes and comes back on its own. It has "
     "been doing this for {days}. The {led} when it drops."),
    ("slow_speed", False,
     "I pay for the {plan} but I am only getting {speed} on a wired connection at any time "
     "of day. Can you check the line?"),
    ("wifi_range", True,
     "The wifi does not reach the back of the house since you replaced my {device}. The "
     "connection itself works fine next to the box."),
    ("evening_drops", False,
     "Every evening between 7 and 10 the connection becomes unusable, then it is fine again "
     "in the morning. This has happened for {days}."),
    # --- billing -------------------------------------------------------------------------- #
    ("double_charge", False,
     "I have been charged {amount} twice this month for the same {plan}. Please refund the "
     "duplicate payment."),
    ("unknown_debit", False,
     "There is a direct debit of {amount} on my account that I did not authorise. I want it "
     "cancelled and explained."),
    ("bill_after_cancel", False,
     "I cancelled {days} ago and you have billed me {amount} again. This is the {nth} this "
     "has happened."),
    ("charged_while_down", False,
     "You have billed me the full {amount} for a month in which the service was out for "
     "{days}. I want that period credited."),
    # --- churn / complaint ---------------------------------------------------------------- #
    ("cancel_threat", False,
     "This is the {nth} I have had to contact you about the same fault. If it is not fixed "
     "today I am cancelling the {plan} and moving to another provider."),
    ("regulator", False,
     "I have had no working service for {days} and no engineer has been sent. I am filing a "
     "formal complaint with the regulator unless someone contacts me today."),
    # --- routine (keeps the low band populated) -------------------------------------------- #
    ("routine_upgrade", False,
     "Could you tell me what it would cost to move from my current {plan} to a faster one? "
     "No rush, just planning ahead."),
    ("routine_appointment", False,
     "I have an engineer visit booked for next week. Could you confirm the time window and "
     "whether I need to be home for it?"),
    ("routine_move", False,
     "I am moving house in {days} and would like to take my {plan} with me. What is the "
     "process?"),
    ("routine_password", True,
     "I would like to change the wifi password on my {device}. Where do I find the current "
     "one?"),
)


def _fill(text: str, rng: random.Random) -> str:
    """Fill every `{slot}` from SLOTS. An unknown slot is a typo in a template, not input."""
    out = text
    for name, options in SLOTS.items():
        token = "{" + name + "}"
        while token in out:
            out = out.replace(token, rng.choice(options), 1)
    if "{" in out:
        raise KeyError(f"unfilled slot in template: {out}")
    return out


def extract(count: int = 700, seed: int = SEED) -> list[SyntheticRequest]:
    """`count` requests spread evenly over the template bank, deterministic under `seed`."""
    rng = random.Random(seed)
    records: list[SyntheticRequest] = []
    for index in range(count):
        template_id, device_relevant, text = TEMPLATES[index % len(TEMPLATES)]
        body = rng.choice(OPENERS) + _fill(text, rng) + rng.choice(CLOSERS)
        records.append(
            SyntheticRequest(
                template_id=template_id,
                text=body,
                device_relevant=device_relevant,
            )
        )
    rng.shuffle(records)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=700)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--show", type=int, default=5, help="print N filled examples")
    args = parser.parse_args()

    records = extract(args.count, args.seed)
    counts = Counter(r.template_id for r in records)
    print(f"synthetic requests: {len(records)} from {len(TEMPLATES)} templates")
    print(f"per template: min {min(counts.values())}, max {max(counts.values())}")
    print(f"device-relevant: {sum(1 for r in records if r.device_relevant)}")
    unique = len({r.text for r in records})
    print(f"unique texts: {unique} ({100 * unique / len(records):.1f}%)")
    for record in records[: args.show]:
        print(f"\n[{record.template_id}] {record.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Check it before wiring it in:

```powershell
& $PY TriageModel\extract\extract_synthetic.py --count 700 --show 8
```

Verified output on this bank: `26 templates`, `per template: min 26, max 27`,
`device-relevant: 215`, `unique texts: 674 (96.3%)`. The gate is **unique texts above 90%** , 
slot filling plus the openers/closers is what stops 700 records collapsing into 26 repeated
sentences, and an encoder trained on repeats learns the template rather than the complaint.
If you fall below it, add options to the thinner `SLOTS` lists; do not add near-duplicate
templates.

Two properties of the bank are deliberate and should not be "fixed":

- `URGENT:` sometimes lands on a routine question. That is a real thing customers do, and it
  is a direct test of the rubric's "urgency is impact, not tone" rule ,  the teacher should
  still label it `low`.
- The wording is aligned with `MVP/api/pipeline/signals.py`'s lexicons (`whole street`,
  `my area`, `no dial tone`, `called twice`), so the rule prefill produces meaningful hints.
  Hints, not answers.

### 2.3 Edit `TriageModel/extract/compose.py`

Four small changes.

**(a) Import it**, next to the other extractors:

```python
import extract_synthetic
```

**(b) Let `_pick_images` be driven by a flag as well as by intent.** Synthetic scenarios are
not in the Bitext intent vocabulary, so they need their own eligibility signal. Change the
signature and the first two lines only:

```python
def _pick_images(
    intent: str,
    pool: dict[str, list[ImageEvidence]],
    rng: random.Random,
    *,
    eligible: bool | None = None,
) -> list[ImageEvidence]:
    """0-2 plausible images. Device-ish intents get them; billing intents never do.

    `eligible` overrides the intent lookup, for records that carry no Bitext intent.
    """
    if eligible is None:
        eligible = intent in DEVICE_INTENTS
    if not eligible or not pool:
        return []
    ...   # rest unchanged
```

**(c) Emit the synthetic records** in `compose()`. Add a `synthetic` parameter, and build the
tickets after the Bitext loop and before the audio loop:

```python
def compose(limit: int = 2800, seed: int = SEED, synthetic: int = 700) -> list[UnifiedTicket]:
    ...
    for position, record in enumerate(extract_synthetic.extract(synthetic, seed)):
        tickets.append(
            _build_ticket(
                ticket_id=_new_id("SYN", rng),
                text=record.text,
                modality=Modality.text,
                channel=rng.choice(CHANNELS_TEXT),
                language="en",
                images=_pick_images("", image_pool, rng, eligible=record.device_relevant),
                created_at=now - timedelta(minutes=position, seconds=30),
                bitext_flags=None,          # no Bitext ground truth: the rules fill the flags
                metadata={
                    "source": "synthetic_telecom",
                    "template_id": record.template_id,
                },
                rng=rng,
            )
        )
```

**(d) Expose it on the CLI**, and add one line to `summarise()` (`Counter` is already
imported there) right after the `records:` print:

```python
    parser.add_argument("--limit", type=int, default=2800, help="Bitext records to sample")
    parser.add_argument("--synthetic", type=int, default=700, help="synthetic telecom records")
    ...
    tickets = compose(limit=args.limit, seed=args.seed, synthetic=args.synthetic)
```

```python
    sources = Counter(str(t.metadata.get("source", "?")) for t in tickets)
    print(f"sources:        {dict(sources)}")
```

Note the Bitext default drops from 3500 to 2800, so the corpus total stays ~3 500 at roughly
80/20. `_build_ticket` needs no change: it already calls the MVP's own
`pipeline.signals.extract`, which will find the outage, urgency and repeat-contact keywords in
the synthetic text and prefill `service_down`, `outage_scope`, `urgency_keywords`,
`repeat_contact` and `sentiment` ,  as hints, which the teacher may override.

### 2.4 Edit `TriageModel/label/validate.py`

Add a per-source breakdown. Averaging a low-urgency e-commerce half with a fault-heavy
synthetic half produces a table that describes neither. `Counter`, `PriorityBand` and
`_percent` are already in that module; add the function next to `self_agreement`, then call
it from `report()` on the line after `print(f"sources: {dict(sources)}")`:

```python
    by_source(labelled)
```

```python
def by_source(labelled: list[UnifiedTicket]) -> None:
    """Urgency and department per `metadata.source`.

    The two halves of the corpus are different distributions on purpose -- Bitext is
    e-commerce and legitimately low-urgency, the synthetic half carries the faults -- so a
    single combined table hides whether either half landed.
    """
    sources = sorted({str(t.metadata.get("source", "?")) for t in labelled})
    for source in sources:
        rows = [t for t in labelled if str(t.metadata.get("source", "?")) == source]
        urgencies = Counter(t.triage.urgency.value for t in rows)
        departments = Counter(t.triage.department.value for t in rows)
        print(f"\nsource: {source}  ({len(rows)} records)")
        for band in (b.value for b in PriorityBand):
            print(f"  {band:<9}{_percent(urgencies.get(band, 0), len(rows))}")
        print("  departments: " + ", ".join(f"{k}={v}" for k, v in departments.most_common()))
```

---

## 3. Generate the unlabelled corpus

Quick check first ,  a 500-record corpus in a few seconds, so a broken edit surfaces before
the full build:

```powershell
cd d:\DSEP22
& $PY TriageModel\extract\compose.py --limit 300 --synthetic 200 `
      --out d:\DSEP22\TriageModel\data\unlabelled_check.jsonl
```

These edits were run end to end before this runbook was written; that command produces
`records: 511`, `sources: {'bitext': 300, 'synthetic_telecom': 200, 'call_centre': 11}`,
`with images: ~115`, and every record passes `validate_ticket`. Delete
`unlabelled_check.jsonl` afterwards, then build the real corpus:

```powershell
& $PY TriageModel\extract\compose.py
```

Expect roughly (measured: the Bitext half contributes ~50 `service_down` and ~54 urgency-word
records, the synthetic half ~270 and ~194):

```
records:        3511
modalities:     {'text': 3500, 'audio': 11}
sources:        {'bitext': 2800, 'synthetic_telecom': 700, 'call_centre': 11}
with images:    750-900
service_down:   ~320          <- was 63 before the synthetic half
urgency words:  ~250
```

If `service_down` is still under 150, the synthetic records are not reaching
`pipeline.signals.extract` ,  check step 2.3(c).

Then the cheap gate:

```powershell
& $PY TriageModel\label\validate.py --dry
```

It validates every record against the schema, confirms the prompt renders for each, and
prints an approximate token count. **STOP if it does not print `OK ,  safe to spend tokens.`**
A corpus bug found here costs seconds; found after the labelling run it costs the whole run.

---

## 4. Label

### 4.1 Smoke run ,  30 records, read them yourself

```powershell
& $PY TriageModel\label\run_labelling.py --provider ollama --workers 2 --limit 30 `
      --output d:\DSEP22\TriageModel\data\labelled_smoke.jsonl
```

`--output` is not optional here. `run_labelling.py` writes only the records it labelled, so a
`--limit 30` run with the default output would replace `labelled.jsonl` with 30 rows.

Time it. That wall clock ÷ 30 × 3511 ÷ 2 is your full-run estimate (§1).

Print the sample and read all 30:

```powershell
& $PY -c @'
import json
path = r'd:\DSEP22\TriageModel\data\labelled_smoke.jsonl'
for line in open(path, encoding='utf-8'):
    d = json.loads(line)
    t = d['triage']
    print('')
    print('[{}/{}] {} / {}  ({})'.format(t['urgency'], t['priority_score'],
          t['department'], t['intent'], d['metadata'].get('source')))
    print('  ' + ' '.join(d['request']['text'].split())[:180])
    print('  why:  ' + str(t['rationale'])[:180])
    pre = d['metadata'].get('prefilled_signals') or {}
    changed = [f for f in ('service_down', 'payment_related', 'repeat_contact',
                           'offensive', 'polite')
               if bool(pre.get(f)) != bool(d['signals'][f])]
    print('  overrode: ' + (', '.join(changed) or 'nothing'))
'@
```

Checklist ,  all five must hold:

1. **Band matches score**: critical 80 to 100, high 60 to 79, normal 35 to 59, low 0 to 34. (The runner
   clamps the score into the band, so a mismatch here means the *band* is wrong.)
2. **Department matches the text**, not the keywords: multi-premises outage →
   `network_operations`; someone needed on site → `field_service`; one customer's device or
   login → `technical_support`; cancelling or threatening a regulator → `retention`.
3. **Urgency is not anger.** A furious customer asking a routine question is `normal`. A
   politely reported street outage is `high` or `critical`. If the model is grading tone,
   the rubric is not landing.
4. **Rationale is specific.** "static equation", "the customer is upset", or the same sentence
   on every row means the model is not reasoning about the ticket.
5. **Signals were overridden at least sometimes.** Compare `metadata.prefilled_signals` with
   `signals`. A teacher that never contradicts the keyword rules is a slower copy of them.

**STOP if the sample fails.** Fix `label/prompt.py` ,  the `SYSTEM` rubric and the `FEW_SHOT`
examples ,  and then **increment `PROMPT_VERSION` in `label/run_labelling.py`**. That constant
is part of the cache key. Without the bump the old answers replay out of
`data/label_cache.json` and your prompt edit does nothing at all. Re-run the smoke test.

Delete `labelled_smoke.jsonl` when satisfied; the cache keeps those 30 answers, so they cost
nothing on the full run.

### 4.2 Full run

```powershell
& $PY TriageModel\label\run_labelling.py --provider ollama --workers 2 `
      --temperature 0.3 --repeat-subset 200
```

- Progress prints every 50 records with cache hits and failures.
- **It is resumable.** Ctrl-C and re-run: everything already answered comes back from the
  cache for free. Do not restart from a clean cache after an interruption.
- `--repeat-subset 200` labels the first 200 records a second time, with a different cache
  salt so it is a genuinely independent sample, and writes `data/labelled_repeat.jsonl`. That
  is the input to the self-agreement gate ,  run it in the same command rather than separately.
- Non-zero exit means some records failed; the ids and errors print at the end. A handful is
  normal (a timeout, a truncated JSON). Re-run the same command to fill them in from cache
  plus retries. If more than ~2% fail repeatedly, go to §8.

What the runner does to each answer, so you can read the output correctly: the priority score
is clamped into its band; `triage.source` is set to `llm` and `model_version` to
`ollama:<tag>`; the corrected signals overwrite the nine boolean flags plus `sentiment`,
`sentiment_score`, `outage_scope`, `urgency_keywords`, `fault_leds` and `error_codes`, while
the account-context scores the teacher cannot see are preserved; and the rule prefill is kept
under `metadata.prefilled_signals` for the override check.

---

## 5. Gates

```powershell
& $PY TriageModel\label\validate.py
```

Every row must pass. STOP and fix the named cause ,  do not proceed to training.

| Gate | Threshold | What a failure means |
|---|---|---|
| `schema invalid` | 0 | Corpus bug, not a label bug. Back to §3. |
| self-agreement `department` and `urgency` | ≥ 0.80 | The prompt is ambiguous. This is the ceiling on the distilled model ,  a student cannot be more consistent than its teacher. Fix `prompt.py`, bump `PROMPT_VERSION`, relabel. Do not "fix" it by lowering the temperature below 0.3; that hides the ambiguity instead of removing it. |
| urgency spread, synthetic half | every band ≥ 2%, `critical` > 0 | The template bank is not landing, or the teacher is grading tone rather than impact. Check §2.2 output, then the rubric. |
| `band vs score violations` | 0 | Clamping is broken; the corpus is inconsistent. |
| `intent/department mismatches` | < 10% of checkable | The taxonomy and the routing rules disagree. Read ten mismatches: if the text justifies them, extend `INTENT_DEPARTMENTS`; if not, sharpen the department definitions in the prompt. |
| `signal overrides` | non-zero on several fields | The teacher only ever agreed with the keyword rules, so it added no information over the static equation. |

Also read the per-source tables from §2.4. Expected shape: the Bitext half heavily `low` with
some `normal` ,  that is correct, it is e-commerce ,  and the synthetic half spread across all
four bands with `network_operations` and `field_service` populated. If both halves look the
same, the teacher is ignoring the text.

---

## 6. Gold slice and human review

```powershell
& $PY TriageModel\label\make_gold.py
```

Writes 150 records to `data/gold.jsonl`, stratified over (urgency × department) so the rare
combinations survive, and writes `data/train.jsonl` with those ids removed ,  scoring a model
against rows it trained on measures memorisation.

The slice is written with `metadata.human_reviewed = false`. Review it:

```powershell
& $PY TriageModel\label\make_gold.py --review
```

Read all 150. Correct what is wrong by editing the `triage` block in `data/gold.jsonl`
directly, and on any row you changed also add `"corrected": true` to its `metadata` ,  the
snippet below uses that marker to reset `triage.source` to `human`, which is what keeps a
corrected row out of any "the teacher said X" tally. Then flip the reviewed flag:

```powershell
& $PY -c @'
import json, pathlib
p = pathlib.Path(r'd:\DSEP22\TriageModel\data\gold.jsonl')
rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
for r in rows:
    r['metadata']['human_reviewed'] = True
    if r['metadata'].get('corrected'):
        r['triage']['source'] = 'human'
p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
             encoding='utf-8')
print(len(rows), 'rows marked reviewed')
'@
```

An unreviewed gold set is just more teacher output, and a score against it only says the
student imitated the teacher ,  which was never the question.

---

## 7. Train and report

```powershell
& $PY TriageModel\train\train_triage.py
```

Writes `artifacts/triage_multitask.pt` and `artifacts/score_table.json`, and logs to MLflow
under `MVP/mlruns`. The embedding cache in `data/embedding_cache/` is keyed by content hash,
so stale entries are never reused ,  leave it alone.

Reporting rules. Break any of these and the numbers mislead exactly the way the current score
table does:

- **Never quote a headline urgency accuracy without the urgency distribution beside it.** The
  existing `acc_urgency = 0.9333` was a constant-`low` predictor.
- Report the Bitext and synthetic slices **separately**. Synthetic text is generated; a score
  on it is a score on your own templates, not on real traffic.
- Quote **de-duplicated** Bitext numbers only (`model testing/README.md`, caveat 1) ,  the raw
  corpus is template-generated and duplicates straddle any split.
- ASR rows are noisy text; notebook 05's shifted-split scores are the honest ones for
  anything reading transcripts.
- State the teacher in every table: `ollama:<tag>`, and the self-agreement number, which is
  the ceiling on everything below it.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ollama circuit breaker is open after repeated failures` | Three consecutive failures opened the breaker; it half-opens after 30 s | `ollama serve` is not running, or the model tag is not pulled. Fix that, wait 30 s, re-run ,  the cache keeps the completed work. |
| Every call takes the full 300 s then fails | Model not pulled, so the server is downloading it, or the tag does not exist | `ollama list`, then `ollama pull <tag>`. Cloud tags need `ollama signin`. |
| `ModuleNotFoundError: No module named 'schema'` | Wrong working directory | Run from `d:\DSEP22`, by script path. |
| Pydantic type error about two different `UnifiedTicket` classes | `MVP/api/schema.py` (the re-export shim) got imported before `TriageModel/schema.py` | Do not add `MVP/api` to `sys.path` yourself; the `_paths` bootstrap already orders it correctly. |
| Prompt edits have no effect | `PROMPT_VERSION` not bumped, so cached answers replay | Increment `PROMPT_VERSION` in `run_labelling.py`. |
| Many `no JSON object in response` failures | Older Ollama build ignoring the JSON-Schema `format` field, or a weak model | The provider already retries once with an explicit "JSON only" turn. If it persists, update Ollama, or move to a stronger tag. Do not loosen the response schema. |
| Run got slower and slower | `--workers` above 2 | Effective concurrency is capped at 2 by the shared semaphore; extra threads only queue and hold timeouts open. |
| `labelled.jsonl` suddenly has 30 rows | A `--limit` run without `--output` | Re-run §4.2; the cache makes it nearly free. |
| Self-agreement is high but the labels look wrong | The teacher is consistently wrong ,  often grading tone as urgency | A prompt problem, not a sampling problem. Fix the rubric, bump the version, relabel. |

---

## 9. Definition of done

- [ ] `data/labelled.jsonl`, `labelled_repeat.jsonl`, `train.jsonl`, `gold.jsonl` all
      regenerated after the corpus fix ,  no file predates §2.
- [ ] Every row's `metadata.labelled_by` starts with `ollama:`. No row says `heuristic:`.
      Check: `& $PY -c "import json,collections;print(collections.Counter(json.loads(l)['metadata']['labelled_by'] for l in open(r'd:\DSEP22\TriageModel\data\labelled.jsonl',encoding='utf-8')))"`
- [ ] `validate.py --dry` prints OK; `validate.py` passes every gate in §5.
- [ ] Urgency spans all four bands, with `critical` non-zero in the synthetic half.
- [ ] `gold.jsonl` has 150 rows with `human_reviewed = true`, and its ids appear nowhere in
      `train.jsonl`.
- [ ] `artifacts/score_table.json` regenerated, reported per source, with the urgency
      distribution and the teacher's self-agreement quoted alongside it.
- [ ] `TriageModel/README.md` updated: the corpus is now Bitext + synthetic telecom + ASR,
      and the teacher is named.
