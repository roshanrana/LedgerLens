# LL-2 — Masked adjudication requests and live backends

**Depends on:** LL-0 · **Status:** in_progress

## Goal
Every payload that reaches a model is masked, and the adjudicator contract that the fake
implements gets three live implementations behind one factory: `openai_compat` (Ollama,
vLLM), `bedrock`, `anthropic`. The fake remains the default and nothing in the golden
replay changes.

## Read first
- `docs/05-langgraph-review-gate-design.md` §4, §5 (frozen)
- `ledgerlens/llm/schemas.py`, `fake.py`, `cache.py`, `masking.py`, `__init__.py`
- `tests/unit/test_llm_cache.py`
- `C:\Code-Central\drydock\drydock\providers\backends.py` and `llm.py` for a working reference of the three adapters and fence-tolerant JSON parsing (same author); port the ideas, not the Pydantic dependency — LedgerLens is dataclasses and stdlib.

## Scope (only these files)
- `ledgerlens/llm/live.py` (new), `ledgerlens/llm/schemas.py`, `ledgerlens/llm/fake.py` (only `CachedLLMAdjudicator.stats()` and the client type hint), `ledgerlens/llm/__init__.py`
- `configs/llm/{fake,ollama,vllm,bedrock,anthropic}.json` (new)
- `tests/unit/test_masking.py`, `tests/unit/test_llm_live.py` (new)
- Do NOT touch `ledgerlens/agents/`, `ledgerlens/api/`, `ledgerlens/cli.py`, `ledgerlens/persistence/`, `ledgerlens/mcp/` (other agents own them).

## Acceptance criteria
1. `build_adjudication_request` sends `mask_transaction(pair.left.compact())` / right; test asserts no raw counterparty or reference string appears anywhere in the request, and that `computed_features`/`policy` are unchanged so `DeterministicFakeLLM` decisions are identical before and after (cache keys unchanged for the fake).
2. `build_cache_key(pair, policy, model_family=MODEL_FAMILY)` adds a keyword; different families yield different keys; `build_adjudication_request(pair, policy, model_family=...)` passes it through and sets `request.model_family`.
3. `live.py`: `LLMClient` Protocol; `OpenAICompatLLM(base_url, model, api_key=None, *, opener=None, timeout=60)` posting to `{base_url}/chat/completions` with `urllib.request` (injectable `opener` callable for tests, no network), temperature 0, JSON-object response format requested; `BedrockLLM(model_id, region, *, client=None)` via boto3 `converse` behind a lazy import; `AnthropicLLM(model, *, client=None, api_key_env="ANTHROPIC_API_KEY")` behind a lazy import. Each has `.model`, `.usage = {"prompt_tokens": int, "completion_tokens": int, "calls": int}`, and `adjudicate(request) -> LLMDecision`.
4. `build_prompt(request) -> (system, user)`: system states the reconciliation adjudication task, the allowed decisions (`match`, `no_match`, `needs_review`), the exact JSON shape (`decision`, `confidence`, `reason_code`, `explanation`), and that the payload is masked evidence, never instructions; user carries `json.dumps(asdict(request))`-style masked content. `parse_decision(text)` strips code fences, loads JSON, validates via `LLMDecision` (raises `LLMError` with the offending text truncated to 200 chars). Live clients retry once with the parse error appended, then raise `LLMError`.
5. `build_adjudicator(name, cache, *, config_dir=CONFIG_DIR) -> CachedLLMAdjudicator`: reads `configs/llm/<name>.json` (`{"backend": "fake|openai_compat|bedrock|anthropic", "model": ..., "base_url": ..., "api_key_env": ... | null, "region": ...}`); resolves the API key from the named env var (missing → `LLMError` naming the variable; `null` means none needed, as for Ollama); missing optional package → `LLMError("install ledgerlens[bedrock]")`. `CachedLLMAdjudicator.stats()` merges `client.usage` when present.
6. Configs: ollama `http://localhost:11434/v1`, model `qwen2.5-coder:7b`, `api_key_env: null`; vllm `http://localhost:8000/v1`, `VLLM_API_KEY`; bedrock `anthropic.claude-opus-5`, `us-east-1`; anthropic `claude-opus-5`; fake has `backend: fake`. No secrets anywhere.
7. Tests: masking (digit runs, truncation, tokens stable and non-reversible, version tag); OpenAICompat with a fake opener returning a canned chat completion (fenced and unfenced), retry path, error after two bad answers, usage accounting; Bedrock and Anthropic with fake client objects; factory: fake needs no env, ollama needs none, vllm raises naming `VLLM_API_KEY` when unset, unknown name raises; cache-family separation.
8. `.venv/Scripts/python.exe -m unittest discover -s tests` green; `.venv/Scripts/python.exe -m metrics.golden` reports unchanged KPI values.

## Validation
```
.venv/Scripts/python.exe -m unittest tests.unit.test_masking tests.unit.test_llm_live tests.unit.test_llm_cache -v
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe -m metrics.golden
```

## Handoff notes (≤10 lines)
