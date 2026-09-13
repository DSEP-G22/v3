# TriageModel ,  schema, labelled corpus, distilled classifier

The dataset deliverable: the `UnifiedTicket` schema, an unlabelled corpus built from the
three existing corpora, the LLM labelling pass, and the distillation training script.

The thesis is that **an LLM labels a dataset once and a small classifier is distilled from
those labels**, so the runtime never pays LLM cost per ticket. No triage-labelled data
exists, which is why the corpus has to be synthesised first.

## Layout

```
TriageModel/
├── schema.py           THE schema. MVP/api/schema.py re-exports it; never a second copy.
├── schema.json         emitted by `python schema.py`
├── extract/            corpus construction -> data/unlabelled.jsonl
├── label/              prompt, runner, validation, gold slice
├── train/              distillation + baselines -> artifacts/
└── data/               jsonl corpora (git-ignored)
```

## Pipeline

```bash
# 1. corpus  (~3.5k records, balanced over the 27 Bitext intents)
python extract/compose.py

# 2. pre-flight before spending tokens
python label/validate.py --dry

# 3. label ,  small run first, read the output by hand
python label/run_labelling.py --limit 50
python label/run_labelling.py --repeat-subset 200

# 4. report: distributions, consistency, self-agreement
python label/validate.py

# 5. gold slice + training split
python label/make_gold.py

# 6. distil
python train/train_triage.py
```

Labelling is resumable: every answer is cached by a content hash of the prompt, model,
temperature and prompt version, so an interrupted run resumes for free and a prompt edit
correctly invalidates the old labels instead of silently reusing them.

### Running it without a key

`--provider heuristic` swaps in an offline teacher that answers in the same JSON shape using
the static equation. It exists to exercise the chain end to end in CI ,  **not** as a
substitute for the LLM pass. Its labels are the keyword rules by construction, so a student
distilled from them recovers the rules and nothing more, which is the exact failure the LLM
pass exists to avoid. Runs are tagged `heuristic/...` in `labelled_by`.

## The corpus

| Source | Yields |
|---|---|
| Bitext CSV, de-duplicated | ~3.5k text tickets, balanced across 27 intents |
| Cached ASR hypotheses | 11 audio tickets in 7 languages, `noisy_text=true` |
| Router COCO test/valid | 2.3k `ImageEvidence` records keyed by dominant class |

`compose.py` pairs each request with 0 to 2 plausible images ,  device-ish intents get router
photographs, billing intents get none ,  and rule-prefills `Signals` using **the same
extraction code the MVP runs**, so the corpus cannot drift from production behaviour. The
Bitext `intent` column is kept as a weak prior in `metadata`, never in `triage`.

## Gates

| Gate | Threshold | Where |
|---|---|---|
| Schema conformance | every record | `validate.py --dry` |
| LLM self-agreement | ≥ 0.80 on the repeat subset | `validate.py` |
| Distilled macro-F1 | within 5 points of the teacher on `gold.jsonl` | `train_triage.py` |
| Inference latency | < 10 ms/ticket | `train_triage.py` |

Self-agreement is the number that matters: it is the ceiling on the distilled model, because
a student cannot be more consistent than its teacher. Below 0.80, fix the prompt ,  the
labels, not the model, are the bottleneck.

## The model

A shallow multi-task head over frozen MiniLM embeddings concatenated with the 18 engineered
`Signals` features: three softmax heads (intent, department, urgency) and one regression head
for `priority_score`. Freezing the backbone is what keeps inference inside the latency budget.

Baselines follow the notebook-01 patterns ,  TF-IDF+LogReg and MiniLM+LogReg, one dedicated
model per target ,  so the comparison is like-for-like. Every run logs to MLflow
(`MVP/mlruns/mlflow.db`; MLflow 3 retired the bare-filesystem backend).

**The deliverable is the trained model and its score table. It is not wired into the MVP** , 
the static equation is the MVP.

## Caveats

- Quote **de-duplicated** Bitext numbers only (`model testing/README.md`, caveat 1). The raw
  corpus is template-generated and duplicates straddle any split.
- ASR output is noisy text. Notebook 05's shifted-split scores are the honest ones for
  anything reading transcripts.
- Bitext is an e-commerce taxonomy with almost no outage or fault vocabulary, so a
  rule-prefilled corpus finds very little to escalate. Urgency is the label the LLM pass has
  to supply from meaning rather than keywords, and the urgency distribution in
  `validate.py` is the first place to check whether it did.
