# Jarvis TODO

## Memory + Self-Evolve (added 2026-05-13)

Goal: persistent semantic recall + behavior adapts over time without retraining base model.

### Phase 1 — Vector memory (RAG)
- [ ] Pick embedding model: `nomic-embed-text` (local, free, via Ollama) or `text-embedding-3-small` (OpenAI, paid)
- [ ] Pick vector store: Chroma (local, simple) or Qdrant (faster, more features) or sqlite-vec (minimal)
- [ ] Schema: `{id, text, embedding, timestamp, source, access_count, last_accessed}`
- [ ] Retrieval helper: embed query → top-k cosine search (threshold 0.7+) → return chunks
- [ ] Inject top-k into Gemini system prompt before each call

### Phase 2 — Memory writer
- [ ] Post-turn extractor: separate LLM call summarizes "facts/preferences worth remembering" from convo
- [ ] Dedup check before insert (cosine sim > 0.95 → skip or merge)
- [ ] Tag types: `preference`, `fact`, `procedure`, `event`

### Phase 3 — Reflection + decay
- [ ] Nightly job: cluster day's memories → summary memory → store, drop raw
- [ ] Score by recency + access count → drop bottom N% monthly
- [ ] Manual "forget X" command

### Phase 4 — Procedural memory (tool-use logs)
- [ ] Log every command Jarvis ran + outcome (success/fail)
- [ ] Index by intent embedding
- [ ] On new request, retrieve past similar runs → pass as few-shot examples

### Phase 5 — True learning (optional, far future)
- [ ] Collect convo logs quarterly
- [ ] LoRA fine-tune Gemini (if API allows) or local model on Samar-specific data
- [ ] A/B vs base before swap

### Stack decisions still open
- Local-only vs cloud embeddings?
- Run vector DB in-process or as separate service?
- Where to store: alongside `commands/`?

### Notes
- Vector memory ≠ learning. Weights frozen. Just better recall.
- True evolution = retrain. Rare, expensive.
- See lore-vs-real chat 2026-05-13 for full breakdown.
