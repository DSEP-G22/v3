# Sinhala speech recognition

The models behind the `speech` binding, why they were chosen, and the evidence for each
(October 2026). Benchmark code: `DSEP-G22/model-testing`, `src/asr_si_benchmark.py`, run by the
`asr-si-benchmark` workflow
([run 37520098701](https://github.com/DSEP-G22/model-testing/actions/runs/37520098701)); rows in
that repo's `results/asr_sinhala.json`.

## What the speech binding offers

| Binding model id | Source | Role |
|---|---|---|
| `whisper-small-si-run11-int8` | [`SinhaSpeech/whisper-small-sinhala-v6-e6-run11-best`](https://huggingface.co/SinhaSpeech/whisper-small-sinhala-v6-e6-run11-best), pinned `b51781e` | **default** |
| `whisper-small-si-dehanns-lora-int8` | [`dehanns/whisper-small-sinhala-lora-r32-seed-456`](https://huggingface.co/dehanns/whisper-small-sinhala-lora-r32-seed-456), pinned `3d1a454`, LoRA merged into `openai/whisper-small` | alternative |
| `faster-whisper-small-int8` | `openai/whisper-small` | base model alone |

All three are Whisper small (244M parameters), converted to CTranslate2 int8 at image build
(`services/audio/convert.py`, about 250 MB each) and decoded the same way. The audio service
swaps between them live (Admin, Models, Speech).

## The SinhaSpeech model is the run11 model already in use

`SinhaSpeech/whisper-small-sinhala-v6-e6-run11-best` is the renamed
`Yohan2003/whisper-small-sinhala-run11-v6-e6`. The old address now redirects to it, and the
`model.safetensors` at the pinned revision has the same SHA-256
(`8dd5011c585cc75e12c2ac0b24c74f56415edfd364c1f9d1dc9f5467dbe1ab87`). So adding it changed the
source the image is built from, not the weights the service runs. The binding id is unchanged,
so no admin choice is lost.

The image stays pinned to `b51781e` (30 Sep 2026). The later revisions (6 Oct 2026) only rewrite the
model card and remove intermediate checkpoints, but they also ship a `tokenizer_config.json`
saved by transformers 5, which the transformers 4 converter cannot read.

### Its evidence is the Hugging Face model card and dataset only

There is no paper, preprint or peer-reviewed write-up for this model. Everything known about it is on
Hugging Face:

- **Model card.** Full fine-tune of `openai/whisper-small` (no LoRA). Trained 6 epochs (11,556
  steps) at learning rate 3e-5, batch 64, bf16, on one AMD MI300X. SpecAugment was on, and each clip
  had a 0.2 chance each of Gaussian noise (SNR 20 to 30 dB), time stretch (0.9 to 1.1x) and pitch
  shift (±2 semitones). The checkpoint was chosen by best validation WER. The card names the
  SinhaSpeech accessibility platform (a University of Moratuwa DSE project) as its user.
- **Dataset.** [`SinhaSpeech/sinhala-asr-data`](https://huggingface.co/datasets/SinhaSpeech/sinhala-asr-data)
  `stratified_v6`: OpenSLR-52 plus collected YouTube, BizBrains and Linga audio, about 155k
  examples. Split speaker-disjoint into 123,205 train, 15,763 validation and 15,860 test.
  `stratified_v6` canonicalises about 2,954 word spellings (ළ/ල, ණ/න, ZWJ conjuncts, -නං/-නම්).
  The dataset licence is listed as unknown.
- **Results reported on the card** (its own test split):

  | Run | Data | Test WER | Test CER |
  |---|---|---:|---:|
  | run5 | v4, 4 epochs | 19.06% | 4.90% |
  | run6-v5 | v5, 5 epochs | 17.15% | 4.62% |
  | run10-v6 | v6, 5 epochs | 17.17% | 4.71% |
  | **run11-v6 (this model)** | v6, 6 epochs | **16.38%** | **4.43%** |

  Validation per epoch fell from 29.44% to 19.61% WER. The card itself flags eval loss rising
  slightly at epoch 6 (0.128 to 0.132) as "mild divergence worth watching".

These figures are self-reported and have not been independently reproduced. Our own benchmark
(below) is the independent check.

## Our benchmark: conversational Sinhala from YouTube

Data: the first 200 clips (27.5 minutes) of
[`SPEAK-ASR/youtube-sinhala-asr`](https://huggingface.co/datasets/SPEAK-ASR/youtube-sinhala-asr)
`test`. This is unscripted YouTube Sinhala, much of it mixed with English. That is closer to a
customer's voice note than read speech. Decoding matches production: faster-whisper int8,
greedy, VAD, language forced to Sinhala, on 4 vCPU (AMD EPYC 7763). Punctuation is stripped
before scoring, and vowel signs and ZWJ are kept.

| Model | WER | CER | Code-mixed clips WER / CER | Real-time factor |
|---|---:|---:|---:|---:|
| Base whisper-small | 1.202 | 1.174 | 1.144 / 1.022 | 1.81 (loops: "අපි අපි අපි …") |
| **SinhaSpeech run11 (default)** | **0.230** | **0.127** | **0.240 / 0.166** | 0.49 |
| dehanns LoRA r32 seed 456 (alternative) | 0.862 | 0.484 | 0.903 / 0.597 | 0.52 |
| Lingalingeswaran whisper-small-sinhala_v3 | 0.780 | 0.468 | 0.847 / 0.601 | 0.49 |
| hlasith whisper-sinhala-small | 0.915 | 0.556 | 0.944 / 0.653 | 0.55 |

- run11 is the best by a wide margin: CER about 3.7 times lower than any other fine-tune.
- **Caveat:** run11's training pool includes YouTube audio, and SPEAK-ASR's clips are also from
  YouTube, so some overlap is possible. The ranking is consistent with the earlier 10-clip check
  in `docs/changes/2026-10-01-voice-replies-console.md` (run11 CER 0.046 against 0.099 for the
  185k model). Still, read run11's absolute number as optimistic.

## The second model: why dehanns LoRA r32

The request was another fine-tune with real research behind it. We searched Hugging Face, arXiv,
Hugging Face Papers, IEEE Xplore and GitHub. No peer-reviewed Sinhala Whisper paper has released
its weights:

| Research | What it did | Weights released? |
|---|---|---|
| Developing a Sinhala Speech Recognition System Using Whisper, ICARC 2026 (IEEE, [doc 11454008](https://ieeexplore.ieee.org/abstract/document/11454008/)) | Fine-tuned Whisper on 5.83 h of curated data, augmented 4x to 23.3 h. Whisper medium reached 5% WER on news-style speech | No. The code is on [GitHub](https://github.com/sandun131/Sinhala-ASR-Whisper-Small), and it loads the model from a local folder |
| Identifying False Content and Hate Speech in Sinhala YouTube Videos ([arXiv 2402.01752](https://arxiv.org/abs/2402.01752)) | Fine-tuned Whisper on OpenSLR-52; 48.99% WER | No |
| A Low-Resource Speech-Driven NLP Pipeline for Sinhala Dyslexia Assistance ([arXiv 2510.04750](https://arxiv.org/abs/2510.04750)) | Zero-shot Whisper; 34% WER on OpenSLR-63 | Not a fine-tune |
| Qwen3-ASR Technical Report ([arXiv 2601.21337](https://arxiv.org/abs/2601.21337)) plus [`Nerdstorm/Qwen3-ASR-0.6B-Sinhala`](https://huggingface.co/Nerdstorm/Qwen3-ASR-0.6B-Sinhala-8bit) | Sinhala fine-tune of a 0.6B ASR model. The card reports 6.86% CER on OpenSLR-52 and 20.46% on this same YouTube set | Yes, but only as MLX (Apple) and OpenVINO builds. It needs a new runtime and is 2.5x Whisper small's size, so it is not a drop-in for faster-whisper |
| MMS, Scaling Speech Technology to 1,000+ Languages ([arXiv 2305.13516](https://arxiv.org/abs/2305.13516)) | `facebook/mms-1b-all` covers Sinhala through a language adapter | Yes, but it has 1B parameters (about 4 GB) and needs a wav2vec2 runtime. Too large for the VPS |

So the alternative was chosen from the Whisper-small fine-tunes that do release weights, by the
strength of their documented method:

- **dehanns LoRA r32 seed 456.** Low-rank adaptation (LoRA, Hu et al., ICLR 2022,
  [arXiv 2106.09685](https://arxiv.org/abs/2106.09685)) of q/v projections in every attention block,
  rank 32, alpha 32. It is one run of a published series that varies rank (16, 32), seed (123,
  456) and code-switching adapters (sequential, joint), with the training configuration and test
  metrics committed beside the weights. Card: 32,062 train, 4,171 validation and 4,326 held-out
  test clips; test WER 48.6%, CER 12.6%.
- On our benchmark it ties Lingalingeswaran v3 (CER 0.484 against 0.468). That model's card
  documents neither its method nor its test set, and hlasith's card evaluates on 10 clips.

dehanns is well behind run11, so it is an alternative, not a replacement. It is there for an A/B
comparison on live voice notes, or as a fallback if run11's source repository changes again.

## Research the approach rests on

- **Whisper** (Radford et al., "Robust Speech Recognition via Large-Scale Weak Supervision", ICML
  2023, [arXiv 2212.04356](https://arxiv.org/abs/2212.04356)). The base model, and the reason
  zero-shot Sinhala fails: it saw little Sinhala. Our base row shows the looping it produces.
- **Monolingual fine-tuning of Whisper** (BuzzASR, Findings of EMNLP 2026,
  [arXiv 2609.09554](https://arxiv.org/abs/2609.09554)). Language-specialised Whisper fine-tunes
  beat Whisper-large-v3 on 77 of 102 languages, with CER 2.8x lower on average. FLEURS has no
  Sinhala, so BuzzASR has no Sinhala model, but it is the evidence that one fine-tune per language
  (our `speech` and `speech_ta` bindings) is the right shape.
- **SpecAugment** (Park et al., Interspeech 2019, [arXiv 1904.08779](https://arxiv.org/abs/1904.08779)),
  used by run11's training, and the augmentation result in the ICARC 2026 paper above. Both explain
  why run11, trained with heavy augmentation, holds up on noisy, conversational audio.
- **OpenSLR-52** (Kjartansson et al., "Crowd-Sourced Speech Corpora for Javanese, Sundanese,
  Sinhala, Nepali, and Bangladeshi Bengali", SLTU 2018). The read-speech corpus at the base of
  most Sinhala fine-tunes, run11's included.
- **CTranslate2 int8**: same conversion as the Tamil model (see `docs/TAMIL-ASR.md`). Quantising
  the weights does not change the ranking, because every row above was measured int8.
