"""Network-boundary tests use httpx.MockTransport; no service or API key is needed."""

import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, SecretStr


class Answer(BaseModel):
    answer: str
    citations: list[dict]
    gap: str


def settings(**overrides):
    values = dict(
        provider="deepseek",
        deepseek_api_key=SecretStr("unit-test-secret-never-log"),
        deepseek_base_url="https://deepseek.invalid",
        deepseek_model="deepseek-flash",
        ollama_url="http://ollama.invalid",
        embedding_model="nomic-embed-text",
        embedding_dim=768,
        model_timeout=1,
        context_token_budget=7000,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def provider(monkeypatch, handler, *, config=None, logs=None):
    from studyagent.providers import Provider

    original_client = httpx.Client
    monkeypatch.setattr(
        "studyagent.providers.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr("studyagent.providers.time.sleep", lambda _: None)
    return Provider(config or settings(), log_call=(logs.append if logs is not None else None))


def completion(content, usage=None):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content, "reasoning_content": "never store me"}}],
            "usage": usage or {},
        },
    )


def test_real_call_uses_json_schema_and_logs_final_input_without_secrets(monkeypatch):
    from studyagent.context import estimate_tokens

    requests, logs = [], []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion('{"answer":"来自证据","citations":[],"gap":""}', {"prompt_tokens": 321})

    model = provider(monkeypatch, handler, logs=logs)
    result = model.complete("answer", {"question": "什么是梯度？", "evidence": []}, Answer)
    assert result["answer"] == "来自证据"
    sent = requests[0]
    assert sent["model"] == "deepseek-flash"
    assert sent["response_format"] == {"type": "json_object"}
    assert "json" in json.dumps(sent["messages"]).lower()
    assert "citations" in sent["messages"][0]["content"]
    assert logs[-1]["input_tokens"] == estimate_tokens(sent["messages"])
    assert logs[-1]["actual_input_tokens"] == 321
    assert logs[-1]["status"] == "ok"
    assert logs[-1]["input_hash"]
    assert "unit-test-secret" not in json.dumps(logs)
    assert "never store me" not in json.dumps(logs)


def test_bad_json_is_repaired_once_with_safe_validation_error(monkeypatch):
    requests, logs = [], []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return completion("not json")
        return completion('{"answer":"修复后","citations":[],"gap":""}')

    model = provider(monkeypatch, handler, logs=logs)
    result = model.complete("answer", {"question": "测试"}, Answer)
    assert result["answer"] == "修复后"
    assert len(requests) == 2
    assert "JSON" in requests[1]["messages"][-1]["content"]
    assert "JSONDecodeError" in requests[1]["messages"][-1]["content"]
    assert [entry["status"] for entry in logs] == ["invalid_output", "ok"]


def test_repair_exhaustion_raises_instead_of_returning_fake_answer(monkeypatch):
    from studyagent.providers import ProviderError

    calls = []
    model = provider(monkeypatch, lambda r: calls.append(r) or completion('{"wrong":1}'))
    with pytest.raises(ProviderError, match="结构化"):
        model.complete("answer", {"question": "测试"}, Answer)
    assert len(calls) == 2


def test_timeout_is_bounded_and_never_falls_back_to_fake(monkeypatch):
    from studyagent.providers import ProviderError

    calls, logs = [], []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret transport exception", request=request)

    model = provider(monkeypatch, handler, logs=logs)
    with pytest.raises(ProviderError, match="超时") as error:
        model.complete("answer", {"question": "测试"}, Answer)
    assert len(calls) == 3
    assert "secret transport" not in str(error.value)
    assert logs[-1]["status"] == "timeout"


def test_authentication_error_is_not_retried_or_exposed(monkeypatch):
    from studyagent.providers import ProviderError

    calls, logs = [], []
    model = provider(
        monkeypatch,
        lambda r: calls.append(r) or httpx.Response(401, text="unit-test-secret-never-log"),
        logs=logs,
    )
    with pytest.raises(ProviderError, match="认证") as error:
        model.complete("answer", {}, Answer)
    assert len(calls) == 1
    assert "unit-test-secret" not in str(error.value) + json.dumps(logs)


def test_missing_key_fails_before_any_request(monkeypatch):
    from studyagent.providers import ProviderError

    calls = []
    model = provider(monkeypatch, lambda r: calls.append(r), config=settings(deepseek_api_key=SecretStr("")))
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        model.complete("answer", {}, Answer)
    assert not calls


@pytest.mark.parametrize("bad_vector", [[0.1, 0.2], [float("nan")] * 768])
def test_embedding_rejects_wrong_dimension_and_nonfinite_values(monkeypatch, bad_vector):
    from studyagent.providers import ProviderError

    def handler(request):
        assert request.url.path == "/api/embed"
        body = json.loads(request.content)
        assert body["truncate"] is False
        return httpx.Response(200, text=json.dumps({"embeddings": [bad_vector]}))

    model = provider(monkeypatch, handler)
    with pytest.raises(ProviderError, match="向量"):
        model.embed(["测试"])


def test_fake_is_explicit_deterministic_and_input_dependent():
    from studyagent.providers import Provider

    model = Provider(settings(provider="fake"))
    evidence = [{"id": "e-1", "text": "梯度指向函数增长最快的方向。"}]
    first = model.complete("answer", {"question": "梯度是什么", "evidence": evidence}, Answer)
    second = model.complete("answer", {"question": "请解释偏导数", "evidence": evidence}, Answer)
    assert "fake" in first["answer"].lower()
    assert first["answer"] != second["answer"]
    assert first["citations"][0]["evidence_id"] == "e-1"
    assert model.embed(["梯度"])[0] == model.embed(["梯度"])[0]
    assert len(model.embed(["梯度"])[0]) == 768
    assert model.embed(["梯度"])[0] != model.embed(["香蕉"])[0]


def test_context_retains_corrections_and_current_state_under_budget():
    from studyagent.context import build_context, estimate_tokens

    state = {
        "space_id": "space-private",
        "current_concept": "梯度",
        "unresolved": ["偏导数定义"],
        "corrections": ["用户纠正：偏好中文，向量用列向量。"],
    }
    history = [{"role": role, "content": f"{index}：" + "旧讨论内容" * 80}
               for index in range(30) for role in ("user", "assistant")]
    evidence = [{"id": f"e-{i}", "text": "证据内容" * 300} for i in range(10)]
    untouched = copy.deepcopy((state, history, evidence))
    messages = build_context(state, history, evidence, budget=1800)
    serialized = json.dumps(messages, ensure_ascii=False)
    assert estimate_tokens(messages) <= 1800
    assert "用户纠正：偏好中文，向量用列向量。" in serialized
    assert "space-private" in serialized and "偏导数定义" in serialized
    assert "摘要" in serialized
    assert (state, history, evidence) == untouched
    assert messages[0]["role"] == "system"
    assert messages[0] == build_context({}, [], [], budget=1800)[0]


def test_context_preserves_role_order_and_complete_tool_groups():
    from studyagent.context import build_context

    history = [
        {"role": "user", "content": "找证据"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
            {"id": "call_2", "type": "function", "function": {"name": "read", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "一条证据"},
        {"role": "tool", "tool_call_id": "call_2", "content": "另一条证据"},
        {"role": "assistant", "content": "已有证据"},
        {"role": "user", "content": "解释它"},
    ]
    messages = build_context({}, history, [], budget=4000)
    assert messages[-len(history):] == history
    # Incomplete tool blocks must be omitted, never emitted as illegal transcripts.
    broken = history[:3] + history[4:]
    compact = build_context({}, broken, [], budget=1000)
    assert not any(m.get("tool_calls") or m["role"] == "tool" for m in compact)


def test_context_raises_when_protected_state_cannot_fit():
    from studyagent.context import build_context

    with pytest.raises(ValueError, match="预算"):
        build_context({"corrections": ["不能丢失" * 500]}, [], [], budget=100)


def test_fake_supports_service_payloads_and_server_grading():
    from studyagent.providers import Provider
    from studyagent.schemas import Grade, Preference, Teaching

    model = Provider(settings(provider="fake"))
    teaching = model.complete("teach", {
        "concept": {"id": "c-1", "name": "梯度", "description": "变化方向"},
        "mode": "example", "evidence": [{"id": "e-1", "text": "梯度指向增长最快的方向。"}],
        "recent_errors": ["把梯度与负梯度混淆"], "previous_questions": [], "preferences": [],
    }, Teaching)
    assert teaching["correct_index"] == 0
    assert len(set(teaching["options"])) == 4
    assert "梯度指向增长最快" in teaching["options"][0]
    grade = model.complete("grade", dict(teaching, student_answer="0"), Grade)
    assert grade["correct"] is True
    assert model.complete("grade", dict(teaching, student_answer="3"), Grade)["correct"] is False
    preference = model.complete("preference", {"content": "我喜欢详细的中文例子", "existing": []}, Preference)
    assert preference["save"] is True
    assert preference["content"] == "我喜欢详细的中文例子"


def test_fake_respects_explicit_out_of_scope_input():
    from studyagent.providers import Provider
    from studyagent.schemas import EvidenceCheck

    result = Provider(settings(provider="fake")).complete("evidence_check", {
        "question": "这个问题与当前课程无关", "scope": "机器学习",
        "evidence": [{"id": "e-1", "text": "梯度指向增长最快的方向"}],
    }, EvidenceCheck)
    assert result["in_scope"] is False
    assert result["sufficient"] is False


def test_health_probes_only_local_model_inventory_and_never_bills(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"models": [{"name": "nomic-embed-text:latest"}]})

    model = provider(monkeypatch, handler, config=settings(deepseek_api_key=SecretStr("")))
    health = model.health()
    assert not health["ready"]
    assert not health["configured"]
    assert health["embedding"]
    assert len(calls) == 1 and calls[0].url.path == "/api/tags"
    assert "unit-test-secret" not in json.dumps(health)


@pytest.mark.parametrize("status", [429, 503])
def test_transient_http_failure_retries_and_recovers(monkeypatch, status):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(status, text="service detail must not be exposed")
        return completion('{"answer":"恢复","citations":[],"gap":""}')

    model = provider(monkeypatch, handler)
    assert model.complete("answer", {}, Answer)["answer"] == "恢复"
    assert len(calls) == 3


def test_context_keeps_explicit_old_user_correction():
    from studyagent.context import build_context, estimate_tokens

    correction = "纠正：之后统一用列向量表示输入。"
    history = [{"role": "user", "content": correction}] + [
        {"role": "user", "content": "普通历史" * 100} for _ in range(25)
    ]
    messages = build_context({}, history, [], budget=1500)
    assert correction in json.dumps(messages, ensure_ascii=False)
    assert estimate_tokens(messages) <= 1500


def test_final_input_budget_includes_schema_task_payload_and_context(monkeypatch):
    from studyagent.context import build_context, estimate_tokens

    requests, logs = [], []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion('{"answer":"已处理","citations":[],"gap":""}')

    state = {"corrections": ["纠正：使用列向量"], "current_concept": "梯度", "space_id": "s-1"}
    history = [{"role": "user", "content": "旧历史" * 100} for _ in range(30)]
    evidence = [{"id": f"e-{i}", "text": "梯度的教材原文" * 500} for i in range(10)]
    payload = {"question": "梯度是什么？", "state": state, "history": history, "evidence": evidence}
    model = provider(monkeypatch, handler, config=settings(context_token_budget=2400), logs=logs)
    model.complete("answer", payload, Answer, build_context(state, history, evidence, budget=2400))
    final = requests[0]["messages"]
    assert estimate_tokens(final) <= 2400
    assert "纠正：使用列向量" in json.dumps(final, ensure_ascii=False)
    assert "梯度是什么？" in json.dumps(final, ensure_ascii=False)
    assert logs[-1]["evidence_truncated"] is True
    assert logs[-1]["included_evidence_ids"]
    assert logs[-1]["input_tokens"] == estimate_tokens(final)


def test_material_preview_truncation_is_explicit_in_model_input(monkeypatch):
    from studyagent.context import estimate_tokens
    from studyagent.schemas import MaterialCheck

    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion('{"status":"uncertain","reason":"预览不完整","relevant":true,"credible":false,"conflicts":[]}')

    model = provider(monkeypatch, handler, config=settings(context_token_budget=1800))
    model.complete("validate_material", {"scope": "机器学习", "text": "教材内容" * 6000}, MaterialCheck)
    final = requests[0]["messages"]
    assert estimate_tokens(final) <= 1800
    assert '"input_truncated":true' in final[-1]["content"]


def test_fake_teaching_changes_question_with_variant():
    from studyagent.providers import Provider
    from studyagent.schemas import Teaching

    model = Provider(settings(provider="fake"))
    payload = {"concept": {"name": "梯度"}, "mode": "quiz", "evidence": [{"id": "e-1", "text": "梯度是增长最快的方向。"}]}
    first = model.complete("teach", dict(payload, question_variant=1), Teaching)
    second = model.complete("teach", dict(payload, question_variant=2), Teaching)
    assert first["question"] != second["question"]


def test_incomplete_tool_metadata_is_omitted_without_crash():
    from studyagent.context import build_context

    messages = build_context({}, [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
            {"id": "call_2", "type": "function", "function": {"name": "search", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "tool", "content": "bad metadata"},
    ], [], budget=2000)
    assert not any(item.get("tool_calls") or item["role"] == "tool" for item in messages)
