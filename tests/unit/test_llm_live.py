import io
import json
import os
import unittest
import urllib.error
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from ledgerlens.llm import (
    CONFIG_DIR,
    MODEL_FAMILY,
    AnthropicLLM,
    BedrockLLM,
    CachedLLMAdjudicator,
    DeterministicFakeLLM,
    InMemoryLLMCache,
    LLMError,
    OpenAICompatLLM,
    build_adjudication_request,
    build_adjudicator,
    build_cache_key,
    build_prompt,
    parse_decision,
)
from ledgerlens.llm.live import MAX_ATTEMPTS, load_backend_config, strip_fences
from ledgerlens.matching import MatchingPolicy, NormalizedTransaction, generate_candidate_pairs

GOOD_DECISION = {
    "decision": "match",
    "confidence": 0.88,
    "reason_code": "amount_date_and_tokens_align",
    "explanation": "Amounts and dates align and the reference tokens are identical.",
}
GOOD_JSON = json.dumps(GOOD_DECISION)
FENCED_JSON = f"```json\n{json.dumps(GOOD_DECISION, indent=2)}\n```"
RAW_COUNTERPARTY = "Square Coffee Bar LLC"
RAW_REFERENCE = "INV-2026-0451"


def tx(transaction_id, amount, posting_date, description, *, source_system, reference=None, counterparty=None):
    return NormalizedTransaction(
        id=transaction_id,
        account_id="operating",
        source_system=source_system,
        posting_date=posting_date,
        amount=Decimal(amount),
        currency="USD",
        description_raw=description,
        description_normalized=description,
        reference=reference,
        counterparty=counterparty,
    )


def sample_request(model_family=MODEL_FAMILY):
    left = tx("bank-1", "-89.99", "2026-05-10", "SQ COFFEE BAR NYC", source_system="bank",
              reference=RAW_REFERENCE, counterparty=RAW_COUNTERPARTY)
    right = tx("ledger-1", "89.99", "2026-05-11", "Square Coffee Bar New York", source_system="ledger",
               reference=RAW_REFERENCE, counterparty="Square Coffee Bar")
    policy = MatchingPolicy(date_window_days=3)
    pair = generate_candidate_pairs([left], [right], run_id="run-live", policy=policy)[0]
    return pair, policy, build_adjudication_request(pair, policy, model_family=model_family)


def chat_completion(text, *, prompt_tokens=120, completion_tokens=30):
    return {
        "id": "chatcmpl-test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
        self.closed = False

    def read(self):
        return self._body

    def close(self):
        self.closed = True


class FakeOpener:
    """Replays canned bodies in order and records every request it received."""

    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        body = self._bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body)

    def payload(self, index=0):
        return json.loads(self.requests[index].data.decode("utf-8"))


class PromptAndParsingTest(unittest.TestCase):
    def test_build_prompt_states_contract_and_carries_masked_payload_only(self):
        _, _, request = sample_request()
        system, user = build_prompt(request)

        for token in ("match", "no_match", "needs_review", "decision", "confidence", "reason_code", "explanation"):
            self.assertIn(token, system)
        self.assertIn("reconciliation", system.lower())
        self.assertIn("masked", system.lower())
        self.assertIn("instruction", system.lower())
        self.assertIn(request.pair_id, user)
        self.assertIn(request.left["counterparty_token"], user)
        self.assertNotIn(RAW_COUNTERPARTY, user)
        self.assertNotIn(RAW_REFERENCE, user)
        self.assertEqual(json.loads(user.split("\n", 1)[1])["cache_key"], request.cache_key)

    def test_parse_decision_accepts_plain_fenced_and_prose_wrapped_json(self):
        for text in (GOOD_JSON, FENCED_JSON, f"Sure, here it is:\n{GOOD_JSON}\nHope that helps."):
            decision = parse_decision(text)
            self.assertEqual(decision.decision, "match")
            self.assertAlmostEqual(decision.confidence, 0.88)
            self.assertEqual(decision.reason_code, GOOD_DECISION["reason_code"])

    def test_strip_fences_handles_fence_without_language(self):
        self.assertEqual(strip_fences("```\n{\"a\": 1}\n```"), '{"a": 1}')
        self.assertEqual(strip_fences("  {\"a\": 1}  "), '{"a": 1}')

    def test_parse_decision_rejects_bad_shapes_with_truncated_excerpt(self):
        long_garbage = "not json at all " * 40
        with self.assertRaises(LLMError) as ctx:
            parse_decision(long_garbage)
        message = str(ctx.exception)
        self.assertNotIn(long_garbage, message)
        self.assertIn(long_garbage[:60], message)
        self.assertLessEqual(len(message), 200 + 80)

        with self.assertRaises(LLMError):
            parse_decision(json.dumps({"decision": "maybe", "confidence": 0.5, "reason_code": "x", "explanation": "y"}))
        with self.assertRaises(LLMError):
            parse_decision(json.dumps({"decision": "match", "confidence": 1.7, "reason_code": "x", "explanation": "y"}))
        with self.assertRaises(LLMError) as missing:
            parse_decision(json.dumps({"decision": "match"}))
        self.assertIn("confidence", str(missing.exception))
        with self.assertRaises(LLMError):
            parse_decision(json.dumps([GOOD_DECISION]))
        with self.assertRaises(LLMError):
            parse_decision("{\"decision\": \"match\", ")


class OpenAICompatLLMTest(unittest.TestCase):
    def test_posts_openai_shape_and_parses_unfenced_reply(self):
        _, _, request = sample_request()
        opener = FakeOpener([chat_completion(GOOD_JSON)])
        client = OpenAICompatLLM("http://localhost:11434/v1/", "qwen2.5-coder:7b", opener=opener, timeout=7)

        decision = client.adjudicate(request)

        self.assertEqual(decision.decision, "match")
        http_request = opener.requests[0]
        self.assertEqual(http_request.full_url, "http://localhost:11434/v1/chat/completions")
        self.assertEqual(http_request.get_method(), "POST")
        self.assertEqual(http_request.get_header("Content-type"), "application/json")
        self.assertFalse(http_request.has_header("Authorization"))
        self.assertEqual(opener.timeouts, [7])
        payload = opener.payload()
        self.assertEqual(payload["model"], "qwen2.5-coder:7b")
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])
        self.assertNotIn(RAW_COUNTERPARTY, json.dumps(payload))
        self.assertTrue(opener.requests and all(isinstance(r.data, bytes) for r in opener.requests))

    def test_bearer_header_when_api_key_given_and_fenced_reply_parses(self):
        _, _, request = sample_request()
        opener = FakeOpener([chat_completion(FENCED_JSON)])
        client = OpenAICompatLLM("http://localhost:8000/v1", "Qwen/Qwen2.5-Coder-7B-Instruct", "s3cret", opener=opener)

        decision = client.adjudicate(request)

        self.assertEqual(decision.reason_code, GOOD_DECISION["reason_code"])
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer s3cret")

    def test_retries_once_with_parse_error_appended(self):
        _, _, request = sample_request()
        opener = FakeOpener([chat_completion("I think they match."), chat_completion(GOOD_JSON)])
        client = OpenAICompatLLM("http://localhost:11434/v1", "m", opener=opener)

        decision = client.adjudicate(request)

        self.assertEqual(decision.decision, "match")
        self.assertEqual(len(opener.requests), 2)
        retry_user = opener.payload(1)["messages"][1]["content"]
        first_user = opener.payload(0)["messages"][1]["content"]
        self.assertTrue(retry_user.startswith(first_user))
        self.assertIn("I think they match.", retry_user)
        self.assertIn("no JSON object", retry_user)
        self.assertEqual(client.usage["calls"], 2)

    def test_raises_llm_error_after_two_bad_answers(self):
        _, _, request = sample_request()
        opener = FakeOpener([chat_completion("nope"), chat_completion("{\"decision\": \"perhaps\"}")])
        client = OpenAICompatLLM("http://localhost:11434/v1", "m", opener=opener)

        with self.assertRaises(LLMError) as ctx:
            client.adjudicate(request)

        self.assertIn(f"{MAX_ATTEMPTS} attempts", str(ctx.exception))
        self.assertIn(request.pair_id, str(ctx.exception))
        self.assertEqual(len(opener.requests), MAX_ATTEMPTS)
        self.assertEqual(client.usage["calls"], MAX_ATTEMPTS)

    def test_usage_accumulates_across_calls(self):
        _, _, request = sample_request()
        opener = FakeOpener([
            chat_completion(GOOD_JSON, prompt_tokens=100, completion_tokens=20),
            chat_completion(GOOD_JSON, prompt_tokens=110, completion_tokens=25),
        ])
        client = OpenAICompatLLM("http://localhost:11434/v1", "m", opener=opener)

        client.adjudicate(request)
        client.adjudicate(request)

        self.assertEqual(client.usage, {"prompt_tokens": 210, "completion_tokens": 45, "calls": 2})
        self.assertEqual(client.model, "m")
        self.assertEqual(client.model_family, "openai_compat:m")

    def test_transport_errors_become_llm_errors_without_retry(self):
        _, _, request = sample_request()
        http_error = urllib.error.HTTPError(
            "http://localhost:11434/v1/chat/completions", 500, "boom", {}, io.BytesIO(b"server exploded")
        )
        for failure, fragment in (
            (http_error, "HTTP 500"),
            (urllib.error.URLError("connection refused"), "connection refused"),
            ("this is not json", "not JSON"),
            ({"choices": []}, "unexpected chat completion shape"),
        ):
            opener = FakeOpener([failure])
            client = OpenAICompatLLM("http://localhost:11434/v1", "m", opener=opener)
            with self.assertRaises(LLMError) as ctx:
                client.adjudicate(request)
            self.assertIn(fragment, str(ctx.exception))
            self.assertEqual(len(opener.requests), 1)
            if fragment == "HTTP 500":
                self.assertIn("server exploded", str(ctx.exception))


class FakeBedrockClient:
    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": self._texts.pop(0)}]}},
            "usage": {"inputTokens": 200, "outputTokens": 40},
            "stopReason": "end_turn",
        }


class BedrockLLMTest(unittest.TestCase):
    def test_converse_request_shape_and_usage(self):
        _, _, request = sample_request()
        fake = FakeBedrockClient([FENCED_JSON])
        client = BedrockLLM("anthropic.claude-opus-5", "us-east-1", client=fake)

        decision = client.adjudicate(request)

        self.assertEqual(decision.decision, "match")
        call = fake.calls[0]
        self.assertEqual(call["modelId"], "anthropic.claude-opus-5")
        self.assertEqual(call["messages"][0]["role"], "user")
        self.assertIn("maxTokens", call["inferenceConfig"])
        self.assertNotIn("temperature", call["inferenceConfig"])
        self.assertNotIn(RAW_COUNTERPARTY, json.dumps(call))
        self.assertEqual(client.usage, {"prompt_tokens": 200, "completion_tokens": 40, "calls": 1})
        self.assertEqual(client.model_family, "bedrock:anthropic.claude-opus-5")

    def test_retry_then_error_and_sdk_failures(self):
        _, _, request = sample_request()
        fake = FakeBedrockClient(["garbage", "still garbage"])
        with self.assertRaises(LLMError):
            BedrockLLM("anthropic.claude-opus-5", "us-east-1", client=fake).adjudicate(request)
        self.assertEqual(len(fake.calls), 2)

        class Exploding:
            def converse(self, **kwargs):
                raise RuntimeError("AccessDeniedException")

        with self.assertRaises(LLMError) as ctx:
            BedrockLLM("anthropic.claude-opus-5", "us-east-1", client=Exploding()).adjudicate(request)
        self.assertIn("AccessDeniedException", str(ctx.exception))

    def test_missing_boto3_raises_install_hint(self):
        _, _, request = sample_request()
        with mock.patch.dict("sys.modules", {"boto3": None}):
            with self.assertRaises(LLMError) as ctx:
                BedrockLLM("anthropic.claude-opus-5", "us-east-1").adjudicate(request)
        self.assertIn("ledgerlens[bedrock]", str(ctx.exception))


class FakeAnthropicClient:
    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._texts.pop(0))],
            usage=SimpleNamespace(input_tokens=300, output_tokens=50),
            stop_reason="end_turn",
        )


class AnthropicLLMTest(unittest.TestCase):
    def test_messages_create_shape_and_usage(self):
        _, _, request = sample_request()
        fake = FakeAnthropicClient([GOOD_JSON])
        client = AnthropicLLM("claude-opus-5", client=fake)

        decision = client.adjudicate(request)

        self.assertEqual(decision.decision, "match")
        call = fake.calls[0]
        self.assertEqual(call["model"], "claude-opus-5")
        self.assertIn("system", call)
        self.assertEqual(call["messages"], [{"role": "user", "content": build_prompt(request)[1]}])
        self.assertNotIn("temperature", call)
        self.assertNotIn(RAW_COUNTERPARTY, json.dumps(call))
        self.assertEqual(client.usage, {"prompt_tokens": 300, "completion_tokens": 50, "calls": 1})
        self.assertEqual(client.model_family, "anthropic:claude-opus-5")

    def test_retry_then_error_and_refusal(self):
        _, _, request = sample_request()
        fake = FakeAnthropicClient(["no", "{}"])
        with self.assertRaises(LLMError):
            AnthropicLLM("claude-opus-5", client=fake).adjudicate(request)
        self.assertEqual(len(fake.calls), 2)

        refusing = FakeAnthropicClient([GOOD_JSON])
        refusing.messages = SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(content=[], usage=None, stop_reason="refusal")
        )
        with self.assertRaises(LLMError) as ctx:
            AnthropicLLM("claude-opus-5", client=refusing).adjudicate(request)
        self.assertIn("refused", str(ctx.exception))

    def test_missing_sdk_raises_install_hint_before_reading_env(self):
        _, _, request = sample_request()
        with mock.patch.dict("sys.modules", {"anthropic": None}):
            with self.assertRaises(LLMError) as ctx:
                AnthropicLLM("claude-opus-5").adjudicate(request)
        self.assertIn("ledgerlens[anthropic]", str(ctx.exception))


class FactoryTest(unittest.TestCase):
    def test_shipped_configs_have_expected_shape_and_no_secrets(self):
        expected = {
            "fake": ("fake", None),
            "ollama": ("openai_compat", None),
            "vllm": ("openai_compat", "VLLM_API_KEY"),
            "bedrock": ("bedrock", None),
            "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
        }
        for name, (backend, api_key_env) in expected.items():
            config = load_backend_config(name, CONFIG_DIR)
            self.assertEqual(config["backend"], backend, name)
            self.assertEqual(config["api_key_env"], api_key_env, name)
            self.assertEqual(set(config), {"backend", "model", "base_url", "api_key_env", "region"}, name)
            self.assertNotIn("api_key", config)
        self.assertEqual(load_backend_config("ollama")["base_url"], "http://localhost:11434/v1")
        self.assertEqual(load_backend_config("ollama")["model"], "qwen2.5-coder:7b")
        self.assertEqual(load_backend_config("vllm")["base_url"], "http://localhost:8000/v1")
        self.assertEqual(load_backend_config("bedrock")["model"], "anthropic.claude-opus-5")
        self.assertEqual(load_backend_config("bedrock")["region"], "us-east-1")
        self.assertEqual(load_backend_config("anthropic")["model"], "claude-opus-5")

    def test_fake_and_ollama_need_no_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            fake = build_adjudicator("fake", InMemoryLLMCache())
            ollama = build_adjudicator("ollama", InMemoryLLMCache())
        self.assertIsInstance(fake, CachedLLMAdjudicator)
        self.assertIsInstance(fake.client, DeterministicFakeLLM)
        self.assertIsInstance(ollama.client, OpenAICompatLLM)
        self.assertEqual(ollama.client.url, "http://localhost:11434/v1/chat/completions")
        self.assertEqual(ollama.client.model, "qwen2.5-coder:7b")

    def test_vllm_requires_named_env_var(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMError) as ctx:
                build_adjudicator("vllm", InMemoryLLMCache())
        self.assertIn("VLLM_API_KEY", str(ctx.exception))

        with mock.patch.dict(os.environ, {"VLLM_API_KEY": "token"}, clear=True):
            adjudicator = build_adjudicator("vllm", InMemoryLLMCache())
        self.assertIsInstance(adjudicator.client, OpenAICompatLLM)
        self.assertEqual(adjudicator.client._headers()["Authorization"], "Bearer token")

    def test_bedrock_and_anthropic_build_without_importing_sdks(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            bedrock = build_adjudicator("bedrock", InMemoryLLMCache())
            anthropic_client = build_adjudicator("anthropic", InMemoryLLMCache())
        self.assertIsInstance(bedrock.client, BedrockLLM)
        self.assertEqual(bedrock.client.region, "us-east-1")
        self.assertIsInstance(anthropic_client.client, AnthropicLLM)
        self.assertEqual(anthropic_client.client.api_key_env, "ANTHROPIC_API_KEY")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMError) as ctx:
                build_adjudicator("anthropic", InMemoryLLMCache())
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_unknown_and_malformed_configs_raise(self):
        with self.assertRaises(LLMError) as ctx:
            build_adjudicator("does-not-exist", InMemoryLLMCache())
        self.assertIn("does-not-exist", str(ctx.exception))
        with self.assertRaises(LLMError):
            build_adjudicator("../fake", InMemoryLLMCache())
        with TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "odd.json").write_text(json.dumps({"backend": "carrier-pigeon"}), encoding="utf-8")
            (Path(temp_dir) / "nomodel.json").write_text(json.dumps({"backend": "bedrock", "region": "us-east-1"}), encoding="utf-8")
            with self.assertRaises(LLMError):
                build_adjudicator("odd", InMemoryLLMCache(), config_dir=temp_dir)
            with self.assertRaises(LLMError) as missing:
                build_adjudicator("nomodel", InMemoryLLMCache(), config_dir=temp_dir)
        self.assertIn("model", str(missing.exception))

    def test_cached_adjudicator_merges_live_usage_into_stats(self):
        _, _, request = sample_request(model_family="openai_compat:m")
        opener = FakeOpener([chat_completion(GOOD_JSON, prompt_tokens=90, completion_tokens=15)])
        adjudicator = CachedLLMAdjudicator(OpenAICompatLLM("http://localhost:11434/v1", "m", opener=opener), InMemoryLLMCache())

        adjudicator.adjudicate(request)
        adjudicator.adjudicate(request)
        stats = adjudicator.stats()

        self.assertEqual(stats["calls"], 1)
        self.assertEqual(stats["cache_hits"], 1)
        self.assertEqual(stats["prompt_tokens"], 90)
        self.assertEqual(stats["completion_tokens"], 15)
        self.assertEqual(stats["backend_calls"], 1)
        self.assertNotIn("prompt_tokens", CachedLLMAdjudicator(DeterministicFakeLLM(), InMemoryLLMCache()).stats())


class CacheFamilySeparationTest(unittest.TestCase):
    def test_model_family_changes_key_and_request_field(self):
        pair, policy, fake_request = sample_request()
        live_request = build_adjudication_request(pair, policy, model_family="openai_compat:qwen2.5-coder:7b")

        self.assertEqual(fake_request.model_family, MODEL_FAMILY)
        self.assertEqual(live_request.model_family, "openai_compat:qwen2.5-coder:7b")
        self.assertNotEqual(fake_request.cache_key, live_request.cache_key)
        self.assertEqual(live_request.cache_key, build_cache_key(pair, policy, model_family="openai_compat:qwen2.5-coder:7b"))
        self.assertNotEqual(
            build_cache_key(pair, policy, model_family="bedrock:x"),
            build_cache_key(pair, policy, model_family="anthropic:x"),
        )

    def test_fake_and_live_decisions_never_share_cache_entries(self):
        pair, policy, fake_request = sample_request()
        live_request = build_adjudication_request(pair, policy, model_family="openai_compat:m")
        cache = InMemoryLLMCache()
        fake_adjudicator = CachedLLMAdjudicator(DeterministicFakeLLM(), cache)
        opener = FakeOpener([chat_completion(json.dumps(dict(GOOD_DECISION, decision="needs_review")))])
        live_adjudicator = CachedLLMAdjudicator(OpenAICompatLLM("http://localhost:11434/v1", "m", opener=opener), cache)

        fake_decision = fake_adjudicator.adjudicate(fake_request)
        live_decision = live_adjudicator.adjudicate(live_request)

        self.assertFalse(live_decision.cache_hit)
        self.assertEqual(fake_decision.decision, "match")
        self.assertEqual(live_decision.decision, "needs_review")
        self.assertEqual(cache.stats()["entries"], 2)


if __name__ == "__main__":
    unittest.main()
