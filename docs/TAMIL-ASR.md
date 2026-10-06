# Tamil speech recognition

Research and benchmark behind the `speech_ta` binding (October 2026). Benchmark code:
`DSEP-G22/model-testing`, `src/asr_ta_benchmark.py`, run by the `asr-ta-benchmark` workflow
([run 37463770532](https://github.com/DSEP-G22/model-testing/actions/runs/37463770532)); full
write-up in that repo's `results/ASR_TAMIL_BENCHMARK.md`.

## What was added

| | |
|---|---|
| Model | [`vasista22/whisper-tamil-small`](https://huggingface.co/vasista22/whisper-tamil-small) (IIT Madras Speech Lab, Apache-2.0), pinned `ac0d71c`, converted to CTranslate2 int8 at image build by `services/audio/convert.py` |
| Binding | `speech_ta` (Admin → Models, "Tamil speech"): `whisper-small-ta-vasista22-int8` (default) or `faster-whisper-small-int8` (the base model, as before) |
| Swap | the audio service watches the binding every 10 s and swaps the Tamil model between notes, like the Sinhala one on `speech` |
| Cost | one more whisper-small int8 in memory (~250 MB) and ~250 MB in the audio image; same decode speed as the base model |

Language detection is unchanged (`spoken_language` in `services/audio/app/main.py`): only once
a note is routed to Tamil does the fine-tune transcribe it.

## Benchmark: FLEURS ta_in test, 200 clips, production decode settings, 4 vCPU

| Model | WER | CER | Real-time factor |
|---|---:|---:|---:|
| faster-whisper small int8 (base, previous Tamil path) | 0.785 | 0.277 | 0.57 |
| **vasista22/whisper-tamil-small int8** | **0.282** | **0.100** | 0.50 |
| steja/whisper-small-tamil int8 | 0.429 | 0.116 | 0.54 |
| Lingalingeswaran/whisper-small-ta int8 | 0.461 | 0.160 | 0.55 |

vasista22 trained on FLEURS train+dev (this test split is held out but in-domain); steja did too
and still trails it by 15 WER points. FLEURS is Indian Tamil read speech, so expect higher error
on Sri Lankan Tamil voice notes.
