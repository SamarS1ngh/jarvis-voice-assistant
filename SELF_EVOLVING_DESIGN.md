# JARVIS-lite — Self-Evolving Voice Assistant Design

Reference doc. Captures the plan for turning this repo into a personal, on-device, continuously learning voice companion. Read this before resuming work.

Last updated: 2026-06-08.

---

## Table of contents

1. [Goal](#1-goal)
2. [Hardware budget (this laptop)](#2-hardware-budget-this-laptop)
3. [Core idea in plain words](#3-core-idea-in-plain-words)
4. [The six parts of the brain](#4-the-six-parts-of-the-brain)
5. [How one request flows end-to-end](#5-how-one-request-flows-end-to-end)
6. [Continuous observation — how it watches you](#6-continuous-observation--how-it-watches-you)
7. [How watching becomes learning](#7-how-watching-becomes-learning)
8. [Why retraining the big model is dangerous](#8-why-retraining-the-big-model-is-dangerous)
9. [Cold-start seeding (skip the day-1 useless phase)](#9-cold-start-seeding-skip-the-day-1-useless-phase)
10. [Cloud usage decay over time](#10-cloud-usage-decay-over-time)
11. [Scale-up: from nocap notification scoring to laptop companion](#11-scale-up-from-nocap-notification-scoring-to-laptop-companion)
12. [Ask-or-Admit rule (no silent failures)](#12-ask-or-admit-rule-no-silent-failures)
13. [Privacy and kill-switches](#13-privacy-and-kill-switches)
14. [Reference: model choices (June 2026)](#14-reference-model-choices-june-2026)
15. [Reference: embedding choices (June 2026)](#15-reference-embedding-choices-june-2026)
16. [Reference: memory framework choices](#16-reference-memory-framework-choices)
17. [Build order](#17-build-order)
18. [Glossary (plain word → real jargon)](#18-glossary-plain-word--real-jargon)
19. [Source links](#19-source-links)

---

## 1. Goal

A persistent, personalized, environment-aware companion that runs on your laptop. Learns your habits. Talks to you. Calls cloud LLMs only when stuck.

**Not** AGI. **Not** a replacement for thinking. The "intelligence" emerges from memory + observation + pattern matching + automation — not from raw model size.

---

## 2. Hardware budget (this laptop)

| Spec | Value |
|---|---|
| CPU | Ryzen 7 5700U (8 cores, 16 threads, AVX2, ~4.4 GHz max) |
| RAM | 14 GiB total |
| GPU | AMD Vega 7 iGPU — **don't waste time on this**, helps prompt-ingest only, no gain on token generation |
| Disk | 281 GB free |

**Practical ceilings:**
- Phi-4-mini (3.8B Q4): ~3.5 GB RAM, ~20 tokens/sec — fast lane
- Qwen3-7B (Q4): ~4.5 GB RAM, ~10 tokens/sec — smart lane
- Both together: ~8 GB → leaves ~6 GB for OS + Whisper + embeddings + Firefox
- 13B+ models: technically fit but swap to disk → painfully slow (2-4 tok/s) — **skip**

---

## 3. Core idea in plain words

Pretend the assistant is a small office with six workers. Each worker has a job:

1. **Ears** — turn voice into text
2. **Translator** — turn text into number-lists so the computer can compare meaning
3. **Notebook** — remember everything (events, facts, habits)
4. **Pattern-Spotter** — learn your taste by watching what you do and what you reject
5. **Thinker** — reason, plan, reply in natural language
6. **Mouth** — turn text back into voice

A seventh worker — **Phone-a-Friend** — calls the cloud (Gemini/Claude) only when the office can't solve it locally.

The "self-evolving" part: every action you take updates the Notebook + nudges the Pattern-Spotter. Over months, it becomes specifically yours. The big Thinker model itself does **not** get retrained — only the small Pattern-Spotter + Notebook grow.

---

## 4. The six parts of the brain

| # | Plain name | Real jargon | Tool | Size |
|---|---|---|---|---|
| 1 | Ears | Speech-to-Text (STT) | `whisper.cpp` (small.en or distil-medium) | ~500 MB |
| 2 | Translator | Embedding model | `EmbeddingGemma-300M` via llama.cpp | ~200 MB |
| 3 | Notebook | Memory store / vector DB / fact store | Mem0 + DuckDB + sqlite-vec | varies |
| 4 | Pattern-Spotter | kNN retriever + small neural network (multi-head) | custom Python, faiss/hnswlib + PyTorch | ~3 MB |
| 5a | Quick Thinker | Small instruction-tuned LLM | Phi-4-mini (3.8B Q4_K_M) via Ollama | ~3.5 GB |
| 5b | Smart Thinker | Mid-size instruction-tuned LLM | Qwen3-7B (Q4_K_M) via Ollama | ~4.5 GB |
| 6 | Mouth | Text-to-Speech (TTS) | Piper (or Kokoro for nicer voice) | ~100 MB |
| 7 | Phone-a-Friend | Cloud LLM fallback | Gemini / Claude API | n/a |

---

## 5. How one request flows end-to-end

Example: you say *"play lofi"*.

```
1. Ears        → text "play lofi"
2. Translator  → vector [0.2, 0.8, 0.1, ...]  (768 numbers)
3. Notebook    → search 10 most similar past requests
                → finds "play jazz" (yesterday) → opened Spotify
4. Pattern-Spotter:
   - kNN vote      → 95% confidence: action = "open Spotify, search lofi"
   - Neural net    → confirms 0.92
   - Combined      → high confidence
5. Ask-or-Admit gate:
   - slots complete? yes (genre=lofi, action=play)
   - confident? yes (>0.7)
   - tool exists? yes (spotify handler)
   → pass through
6. Action executor → spotify-tui play "lofi"
7. Verify          → spotify process running? yes
8. Mouth           → "Playing lofi" (or stays silent if you set quiet-mode)
9. Watch reaction  → no skip in 5 seconds → label = "good"
10. Notebook updates → vec + features + label = 1.0 stored
    Pattern-Spotter trains one SGD step
```

Total: ~1-2 seconds. No internet call.

**If anything fails at any step**, the Ask-or-Admit gate (section 12) speaks up instead of swallowing it.

---

## 6. Continuous observation — how it watches you

Five background sensors run as low-priority daemons. Each writes events to the Notebook.

| Sensor | What it captures | Tool |
|---|---|---|
| Active window | which app + window title is focused, sampled every few seconds | `xdotool getactivewindow getwindowname` |
| Clipboard | clipboard *type* (URL / code / text / image) — not content unless useful | `xclip` / `xsel` |
| Browser tabs | open URLs + tab counts | tiny WebExtension that posts to local socket |
| File events | create/save/delete in watched dirs | `inotify` (via `pyinotify` or `watchdog`) |
| Time + calendar | clock, day, scheduled events | system + Google/local calendar API |

### What is NOT watched
- Screen pixels (no screenshots unless you ask)
- Mic (only when wake word fires)
- Keystrokes (no keylogger)
- Camera

### Pause / privacy
- Wake-word command "Jarvis sleep" → all sensors off until "Jarvis wake"
- Per-app blacklist (banking app focused → sensors auto-pause)
- Per-domain pause ("private mode 30 min")
- Right-to-forget: `jarvis forget X` → deletes everything related to X across all stores

### How often it writes
Sensor stream is HIGH volume (~10-50 events/min during active use). Stored in DuckDB as a timeseries table, summarized nightly to prevent explosion.

---

## 7. How watching becomes learning

Every event is a row in the Notebook. Each turn the assistant takes is also a row, with a **label** (good / bad / neutral / abstain).

### Where labels come from (no manual effort)

| Behavior signal | Inferred label |
|---|---|
| You confirm ("yes", "thanks", "perfect") | 1.0 |
| You don't cancel within 5 sec | 0.8 (weak positive) |
| You say "no / stop / cancel" within 5 sec | 0.0 |
| You repeat the same command differently | 0.0 for the previous response |
| You explicitly say "remember this" | semantic memory write |
| You say "forget that" | delete + retrain |
| Ambiguous (could be either) | **ABSTAIN** — no label written, don't poison the model |
| Neutral (you walked away) | no label written (NOT 0.5 — that would just add noise) |

### Two learners use these labels

**Memory matcher (kNN)** — finds the 10 most similar past rows when a new request arrives. Recent rows count more (exponential recency, 180-day half-life). Works from row 1.

**Neural net (the head)** — ~500K-1M tiny tunable numbers ("weights"). Each labeled event nudges them via SGD (stochastic gradient descent). Spots general rules the matcher misses ("anything at 3am = low priority").

Both vote. Combined score = `α × P_knn + (1-α) × P_net`. α starts at 0.6 (trust kNN more) and drifts to 0.4 once the net has ~2000 examples.

If they **disagree sharply** (>0.4 apart), the Smart Thinker is asked to tiebreak. If it also can't decide, **Ask the user** (preferred) or call cloud (last resort).

### Procedural memory — learning routines

A separate small Transformer (~2M params, 4 layers, 128 hidden) takes the last 50 events as input and predicts the next probable event. Used for *"user just did A then B → assistant pre-warms C"*.

This is what makes the assistant feel **anticipatory** rather than reactive.

---

## 8. Why retraining the big model is dangerous

Direct continual training of the LLM weights causes:
- **Catastrophic forgetting** — learns your jargon, loses general English
- **Identity drift** — assistant slowly stops sounding like an assistant
- **Reinforcement loops** — amplifies its own mistakes
- **Hallucination spikes** — weights wander to unstable regions

That's why personalization lives in the **Notebook + Pattern-Spotter**, not in the LLM weights.

### Long-term (v3, after ~6 months of clean data)

Once enough labeled data exists, swap from a standalone neural net to a **rank-1 LoRA adapter** on Qwen3-7B (Online-LoRA framework). This personalizes the LLM safely:
- Tiny new weights (~10 MB) sit alongside the base model
- Online-LoRA detects drift (loss plateau) and spawns new adapter params
- EWC (Elastic Weight Consolidation) penalty prevents forgetting general knowledge
- A frozen anchor copy of Qwen3 is kept for benchmark eval

**Do not start with LoRA.** It needs months of clean labels first. Start with the small net.

---

## 9. Cold-start seeding (skip the day-1 useless phase)

Without seeding, day 1 = empty notebook = useless. Fix by pre-loading data **before** first launch.

| Seed type | What | Effort | Win |
|---|---|---|---|
| Persona YAML | 50-100 facts about you (likes, projects, routines, friends) | hours | gives semantic memory a foundation |
| Command bank | 5000 synthetic (utterance, intent, slots, label) tuples generated by **local Qwen3 overnight** (free) | overnight | kNN works from row 1, no more "couldn't reach smart mode" |
| Public datasets | Snips NLU, Fluent Speech Commands, HomeAssistant intents | hour | general voice command breadth |
| Failed-command auto-promotion | every successful Gemini answer → saved as local handler | continuous | second time = local |
| Synthetic head warm-up | offline-train the neural net on the seeded data for ~10 epochs before going live | overnight | net is 70% accurate at boot, not random |

**Net effect:** day-1 cloud usage drops from 95% to 30% before any real interaction.

---

## 10. Cloud usage decay over time

| Phase | Time | Cloud share | What still goes to cloud |
|---|---|---|---|
| 1 (empty + no seed) | day 1 | ~95% | almost everything |
| 1 (seeded) | day 1 | ~30% | novel intents only |
| 2 | week 2 | ~10% | open-ended questions, deep reasoning |
| 3 | month 2 | ~3% | hard reasoning, novel novel queries |
| 4 | month 6+ | ~1-2% | open-ended novel queries only |

Cloud usage never hits zero — open-ended creative reasoning always benefits from a bigger brain. But "depends on cloud" → false. "Falls back rarely" → true.

---

## 11. Scale-up: from nocap notification scoring to laptop companion

The nocap `DESIGN.md` (`~/Documents/projects/nocap/DESIGN.md`) was the seed pattern but designed for phone-scale (~100K rows, single binary scoring). Voice assistant runs at much larger scale. The substrate must change.

| nocap assumption | Voice scale reality | Fix |
|---|---|---|
| ≤100K vectors, brute-force kNN fine | hits 100K in ~weeks (sensors fire continuously) | **ANN index** (HNSW) via `sqlite-vec` or `hnswlib` |
| One SQLite table | 4 data shapes (timeseries, vectors, facts, sequences) | **4 stores** with different decay policies |
| Single binary output (importance 0-1) | intent + slots + action + sentiment + escalate | **multi-head net** (shared trunk, 5 heads) |
| 51 structured features | active-win + app + project + time + clipboard + tabs + files + idle + calendar + audio + battery → 200-500 dims | **wider feature vector** |
| Live SGD on 50K weights | 1M+ events/year, head saturates fast | **bigger trunk (~700K params) + later LoRA on LLM** |
| Pruning deferred to 50K rows | hits in days | **hierarchical summarization mandatory from day 1** |
| Loss ring buffer (1K) for diagnostics | need metrics + audit + replay | **observability layer** |
| Single async process | hot path <500ms, wake-word real-time | **multi-process supervisor (systemd user services)** |
| Encoder frozen, no adaptation | personal vocab (project names, friends) misencoded | **trainable adapter layer on top of encoder** |
| No catastrophic forgetting issue | LoRA on LLM = real risk | **experience replay buffer + EWC** |
| Privacy = "don't store secrets" | continuous observation = far more sensitive | **encryption + redaction rules + per-domain pause + forget API** |

### Revised data stores (4, not 1)

```
HOT       in-RAM             current session, 1-5K items
                              working memory, conversation turns, active sensors

WARM      DuckDB + sqlite-vec   last 30 days
                              events (timeseries), vectors (ANN), facts (SQL)
                              one binary, SQL + vector queries together

COLD      Parquet              30-365 days
                              daily/weekly LLM-generated summaries, compressed

PERMANENT YAML + curated SQLite forever
                              persona facts, trait corrections, kill rules
```

### Revised brain — shared-trunk multi-head

```
input: [embedding 768] + [features 256] = 1024 dims
        │
        ▼
trunk:  1024 → 512 (ReLU) → 256 (ReLU)
        │
        ▼
heads (each is one Linear):
   intent:    256 → 50 classes (softmax)
   slots:     256 → BIO tags per token
   action:    256 → 30 tools (softmax)
   sentiment: 256 → 3 classes
   escalate:  256 → 1 sigmoid (confidence)
```

~700K params. Tiny. Trains all heads jointly. Loss = weighted sum.

### Multi-process supervisor

| Process | Priority | Role | Restart |
|---|---|---|---|
| `wake-stt` | real-time | wake-word + Whisper, low latency | always |
| `sensors` | low | env capture, isolated | always |
| `brain` | normal | LLMs loaded, expensive to restart | on crash |
| `executor` | normal | tool calls, sandboxed | kill+restart if hung |
| `nightly` | idle | summarization, batch training | runs when idle |

Glue: `systemd --user` services + Unix domain sockets. A sensor crash doesn't kill wake-word.

### Hierarchical summarization (mandatory)

Nightly background job during idle (>1 hr no activity):

```
last 24hr raw events
   │
   ▼  Qwen3-7B summarize
"Today: deep work 11pm-2am on voice-assistant.
 Searched embedding models. Mood: focused.
 Failed: 2 cloud calls (Gemini timeout)."
   │
   ▼
store summary, prune raw events older than 7 days
   │
   ▼  weekly: 7 daily summaries → weekly trait
   ▼  monthly: weekly summaries → trait drift report
```

Without this: 1M events/year explodes storage + slows retrieval.

### Hardware budget (revised, with all parts loaded)

| Process | RAM |
|---|---|
| Phi-4-mini Q4 | 3.5 GB |
| Qwen3-7B Q4 | 4.5 GB |
| EmbeddingGemma | 0.3 GB |
| Whisper small | 0.5 GB (unload between wake-words to save) |
| Brain net + sequence model | 0.1 GB |
| DuckDB + sqlite-vec | 0.5 GB |
| OS + Firefox + IDE | 4 GB |
| **Total** | **~13.5 GB** — tight on 14 GB |

Mitigation: unload Whisper between wake-words. Or skip Phi-4-mini, route everything through Qwen3 (slower hot path, saves 3.5 GB).

---

## 12. Ask-or-Admit rule (no silent failures)

**Hard rule:** the assistant must NEVER silently fail or silently guess. If unsure or unable, it must speak up.

### Before action — confidence + capability gate

| Check | If fails | What assistant says |
|---|---|---|
| Slot complete? (required arg missing) | ask for it | *"Remind you when?"* |
| Confident match? (top kNN sim ≥ 0.7 OR head ≥ 0.75) | else ask | *"Did you mean play music or open Spotify?"* |
| Disambiguation? (top-2 within 0.1 of each other) | else ask | *"Two close matches — A or B?"* |
| Tool exists? (action handler registered) | else admit | *"I don't know how to do that yet — logged it."* |

### After action — verify gate

| Verify | If fails | What assistant says |
|---|---|---|
| Action verified (window opened, file changed, process running) | else report | *"Tried opening Spotify, didn't start. Check if installed?"* |
| Cloud reachable (Gemini call returned) | else admit | *"Cloud brain offline, can't help with that one. Try again later."* |

### Replaces nocap's silent abstain

nocap's design says "abstain when ambiguous" — but silently. Voice assistant must use **vocal abstain**: speak that it's abstaining, log it, ask for clarification.

### Implementation hooks
- Every `except: pass` in current `commander.py` / `gemini_brain.py` → must surface a spoken or logged message
- Slot validator before action dispatch
- Post-action verifier (e.g. `xdotool getactivewindow` after "open X")
- Auto-log unknown intents to `missing_capabilities.md` (already partially in place)

---

## 13. Privacy and kill-switches

- **Encryption at rest:** SQLCipher for warm/cold stores. Key in OS keyring.
- **Redaction rules:** before write, regex strips passwords, API keys, credit cards from clipboard/files.
- **Per-app blacklist:** banking app focused → all observers paused. Configurable list.
- **Per-domain pause:** "Jarvis, private mode for 30 min" → all writes off, actions still allowed.
- **Forget API:** `jarvis forget X` → vector + relational + summary scan + delete + audit log entry.
- **Audit log:** every decision row stored — input, prediction, source enum, action, verify result, label. SQLite-backed.

---

## 14. Reference: model choices (June 2026)

| Role | Model | Params | RAM (Q4_K_M) | Speed (CPU) | Why |
|---|---|---|---|---|---|
| Smart thinker (primary) | **Qwen3-7B-Instruct** | 7B | ~4.5 GB | 8-12 t/s | best HumanEval (76.0) under 8B, strong tool/JSON output |
| Quick thinker (hot path) | **Phi-4-mini** | 3.8B | ~3.5 GB | 18-25 t/s | only viable fast lane on 14 GB |
| All-rounder fallback | Llama-3.3-8B | 8B | ~6 GB | 6-10 t/s | best balanced MMLU (73) + MT-Bench (8.1) |
| Instruction follower alt | Mistral-Small-3 (7B) | 7B | ~5 GB | 7-10 t/s | cleanest structured output |
| Too big | Qwen3-14B | 14B | ~8.5 GB | 2-4 t/s | swaps to disk, skip |

Source: see [section 19](#19-source-links).

---

## 15. Reference: embedding choices (June 2026)

| Model | Params | Size | Dim (Matryoshka) | Ctx | MTEB | Why |
|---|---|---|---|---|---|---|
| **EmbeddingGemma-300M** | 300M | ~200 MB | 768 → 128 | 2K | ~60 | **runs in same llama.cpp binary as LLMs** — single stack |
| Nomic Embed v2 | 137M | 274 MB | 768 → 64 | **8K** | 62.39 | MoE, hybrid dense+sparse, best quality/size |
| BGE-M3 | 568M | ~1.2 GB | 1024 | 8K | 64 | heavier, only if quality is the bottleneck |
| all-MiniLM-L6-v2 (old reliable) | 22M | 90 MB | 384 | 512 | 56 | fastest, lowest quality, last resort |
| Static embeddings | tiny | <50 MB | 384 | unlimited | ~48 | **100-400x faster CPU**, use for wake-word hot path only |

**Default:** EmbeddingGemma-300M via llama.cpp. Matryoshka means store 128-dim for fast kNN, encode 768 when precision needed.

---

## 16. Reference: memory framework choices

| Framework | Approach | Lock-in | Best for |
|---|---|---|---|
| **Mem0** | passive fact extraction → vector store → injects relevant memories on prompt. Framework-agnostic. | low | **default for 2026 consumer apps**, 48K+ GH stars |
| Letta (MemGPT) | agent self-edits 3-tier memory (core/recall/archival), owns agent loop | high | autonomous long-horizon agents |
| Zep | temporal knowledge graph scoped per user/session | medium | entity-relation heavy |
| LangMem | LangChain-native | low | LangChain stacks |

**Default:** Mem0 on top of DuckDB + sqlite-vec. nocap pattern (kNN + head) sits **above** Mem0 as the preference scorer, not as the memory store itself.

- Mem0 answers: "what do I remember about this?"
- Pattern-Spotter answers: "what does the user want right now?"

---

## 17. Build order

| Phase | Work | Est. time | Outcome |
|---|---|---|---|
| 1 | Multi-process supervisor (`systemd --user` services + Unix sockets) | 2 days | clean stop/start during dev |
| 2 | Ollama + Phi-4-mini + Qwen3-7B + router into `gemini_brain.py` | weekend | cloud drops ~70% Monday |
| 3 | DuckDB + sqlite-vec warm store schema | 2 days | substrate ready |
| 4 | EmbeddingGemma via llama.cpp + trainable encoder adapter | 2 days | semantic retrieval working |
| 5 | Env sensors (xdotool, xclip, inotify, calendar) | 3 days | continuous observation live |
| 6 | Signal interpreter (labels from behavior) | 3 days | fuel for learning |
| 7 | Multi-head brain (shared trunk + 5 heads) + SGD | 1 week | personal scoring live |
| 8 | **Ask-or-Admit gate** (slots + confidence + capability + verify) | 2 days | no more silent failures |
| 9 | Hierarchical summarizer (nightly LLM job) | 3 days | stores stay healthy |
| 10 | Procedural sequence model (small Transformer over event log) | 4 days | anticipatory routines |
| 11 | Mem0 integration on top of stores | 3 days | episodic/semantic API done |
| 12 | Persona seed + 5000 command bank (Qwen3 overnight gen) + corpus imports | 1 day | day-1 useful |
| 13 | Observability (metrics, audit log, replay-debug, local dashboard) | 1 week | debuggable |
| 14 | Privacy layer (SQLCipher, redaction, pause, forget API) | 1 week | safe to run 24/7 |
| 15 | Tool reliability wrapper (verify, retry, rollback) | ongoing | reliability > intelligence |
| 16 | (~6 mo later) Online-LoRA on Qwen3 + replay buffer + EWC | 2 weeks | LLM itself personalizes |

**Total to v1 (useful daily):** ~6 weeks part-time.
**Total to v2 (self-evolving with LoRA personalization):** ~8 months calendar.

---

## 18. Glossary (plain word → real jargon)

| Plain | Real term | Meaning |
|---|---|---|
| number-list | embedding / vector | fixed-size list of floats representing meaning |
| translator | encoder | model that turns text into embeddings |
| memory matcher | kNN (k-nearest-neighbours) | finds the k closest stored vectors |
| similarity | cosine similarity | [-1, 1] angle between vectors |
| tiny brain | neural network | layers of weighted connections |
| knob | weight / parameter | one tunable number inside a neural net |
| middle layer | hidden layer | layer between input and output |
| smoother | ReLU activation | `max(0, x)` non-linearity in hidden layers |
| squasher | sigmoid | squashes any number to [0, 1] |
| nudge math | backpropagation (backprop) | algorithm for computing gradients across layers |
| nudging algorithm | SGD (stochastic gradient descent) | one weight update per example |
| learn-as-you-go | online learning | training one example at a time, live |
| truth label | label / target | "correct" answer for a given input |
| matcher vs net mix | α (alpha) | weight in `α·P_knn + (1-α)·P_net` |
| recent counts more | recency weighting | `exp(-age / half_life)` weighting of old data |
| half-life | exponential decay constant | time after which weight drops to 0.5 |
| floor on learning rate | LR floor | min learning rate so model never goes fully static |
| boost when surprised | adaptive LR burst | temporary LR boost on loss spike |
| insert-or-update | upsert | one row per stable key; relabeling updates that row |
| stay quiet when unsure | abstain | don't write a label if signal is ambiguous |
| where the label came from | provenance | source channel (click / swipe / manual / etc.) |
| tiny add-on weights | LoRA (Low-Rank Adaptation) | small trainable adapter layered on a frozen base model |
| don't forget the basics | EWC (Elastic Weight Consolidation) | regularization that penalizes changes to important weights |
| replay old examples while learning new | experience replay | random sample of old data mixed into training batches |
| fast neighbour search | ANN (Approximate Nearest Neighbours) | sub-linear kNN via index (HNSW, IVF, etc.) |
| step-by-step planner | sequence model | model that takes a sequence in and predicts the next item |
| OS file event listener | inotify | Linux kernel API for filesystem change notifications |
| fact extraction service | Mem0 | library that extracts and stores facts from conversations |
| three-tier memory | Letta / MemGPT | core (RAM) + recall (disk cache) + archival (cold storage) |

---

## 19. Source links

**Local LLMs (June 2026):**
- [Best Local LLM Models 2026 — sitepoint](https://www.sitepoint.com/best-local-llm-models-2026/)
- [Best Small Language Models 2026 — Local AI Master](https://localaimaster.com/blog/small-language-models-guide-2026)
- [Qwen 3 vs Llama 4 vs Mistral 2026 — promptquorum](https://www.promptquorum.com/local-llms/qwen-vs-llama-vs-mistral)
- [What is the best local LLM for coding 2026 — Medium](https://medium.com/data-science-collective/what-is-the-best-local-llm-for-coding-in-2026-8dab3619ff89)

**Hardware / benchmarks:**
- [llama.cpp CPU vs iGPU benchmark — Medium](https://medium.com/@techhara/llama-cpp-benchmark-cpu-vs-igpu-93b3cc40ece5)
- [llama.cpp Vulkan performance discussion — GitHub](https://github.com/ggml-org/llama.cpp/discussions/10879)

**Embeddings:**
- [Introducing EmbeddingGemma — Google Developers Blog](https://developers.googleblog.com/en/introducing-embeddinggemma/)
- [Best Open-Source Embedding Models in 2026 — BentoML](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
- [Train 400x faster Static Embedding Models — HuggingFace](https://huggingface.co/blog/static-embeddings)

**Memory frameworks:**
- [Mem0 vs Letta vs MemGPT 2026 — TokenMix](https://tokenmix.ai/blog/ai-agent-memory-mem0-vs-letta-vs-memgpt-2026)
- [State of AI Agent Memory 2026 — Mem0](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Agent Memory at Scale 2026 — AgentMarketCap](https://agentmarketcap.ai/blog/2026/04/10/agent-memory-vendor-landscape-2026-letta-zep-mem0-langmem)

**Voice assistant architecture:**
- [Build a Private Local AI Voice Assistant 2026 — Botmonster](https://botmonster.com/smart-home/build-private-local-ai-voice-assistant-2026/)
- [Building a Fully Local LLM Voice Assistant — Towards AI](https://pub.towardsai.net/building-a-fully-local-llm-voice-assistant-a-practical-architecture-guide-6a506aee6020)

**Continual learning:**
- [Write small, learn forever: rank-1 LoRA — Baseten](https://www.baseten.com/research/write-small-learn-forever/)
- [Online-LoRA WACV 2025 — GitHub](https://github.com/christina200/online-lora-official)

**nocap reference (the seed pattern):**
- `~/Documents/projects/nocap/DESIGN.md` — the original on-device personalization design this scales up from.

---

## Bottom line

- Brain ≠ one big model. Brain = many small parts cooperating.
- Smartness = memory + observation + matching + automation. Not raw model size.
- Cloud = backup, not default.
- "Self-evolving" = Notebook grows + Pattern-Spotter nudges with every action. Big LLM weights stay frozen until v3.
- Never silently fail — always Ask or Admit.

When resuming: start at the build phase you stopped on. Each phase is independently testable. Don't try to do all 16 at once.
