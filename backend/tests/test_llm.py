"""The backend adapters, tested against fake transports. Nothing here needs a key or a network."""

import io
import json
import urllib.error
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from phenoctx import llm as llm_module
from phenoctx.llm import (
    DEFAULT_OLLAMA_MODEL,
    AnthropicLLM,
    LLMError,
    LLMFatalError,
    OllamaLLM,
    ToolCall,
    ToolResult,
    Turn,
    select_llm,
)

TOOLS = [{"name": "run_sql", "description": "Run SQL", "input_schema": {"type": "object"}}]
CALL = ToolCall("id-1", "run_sql", {"query": "SELECT 1"})


class Facts(BaseModel):
    number: int


@pytest.mark.parametrize(
    ("env", "backend", "model"),
    [
        ({"ANTHROPIC_API_KEY": "k"}, "anthropic", "claude-opus-5-5"),
        ({"OLLAMA_MODEL": "small"}, "ollama", "small"),
        ({"AGENT_BACKEND": "ollama"}, "ollama", DEFAULT_OLLAMA_MODEL),
        ({"ANTHROPIC_API_KEY": "k", "OLLAMA_MODEL": "small"}, "anthropic", "claude-opus-5-5"),
        ({"AGENT_BACKEND": "ollama", "ANTHROPIC_API_KEY": "k"}, "ollama", DEFAULT_OLLAMA_MODEL),
        ({"AGENT_BACKEND": "OLLAMA", "OLLAMA_MODEL": "small"}, "ollama", "small"),
    ],
)
def test_select_llm(env: dict[str, str], backend: str, model: str) -> None:
    llm = select_llm(env)

    assert llm is not None
    assert (llm.backend, llm.model) == (backend, model)


@pytest.mark.parametrize(
    "env",
    [{}, {"ANTHROPIC_API_KEY": ""}, {"OLLAMA_MODEL": " "}, {"AGENT_BACKEND": "anthropic"}],
)
def test_select_llm_returns_none_when_not_configured(env: dict[str, str]) -> None:
    assert select_llm(env) is None


def test_select_llm_rejects_an_unknown_backend() -> None:
    with pytest.raises(LLMFatalError, match="AGENT_BACKEND"):
        select_llm({"AGENT_BACKEND": "other"})


class FakeOllama:
    """Replaces urlopen, returning canned JSON or raising a canned error."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *replies: Any) -> None:
        self.replies = list(replies)
        self.payloads: list[dict[str, Any]] = []
        monkeypatch.setattr(llm_module.urllib.request, "urlopen", self)

    def __call__(self, request: Any, timeout: float) -> Any:
        self.payloads.append(json.loads(request.data))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())


def ollama_reply(message: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"message": message, "prompt_eval_count": 11, "eval_count": 7, **fields}


def http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("url", code, "error", {}, io.BytesIO(body))  # type: ignore[arg-type]


def test_ollama_request_translates_tools_and_sets_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOllama(monkeypatch, ollama_reply({"role": "assistant", "content": " Done. "}))

    turn = OllamaLLM("small").respond("be fair", TOOLS, [{"role": "user", "content": "hi"}])

    payload = fake.payloads[0]
    assert payload["model"] == "small"
    assert payload["stream"] is False
    assert payload["messages"][0] == {"role": "system", "content": "be fair"}
    assert payload["tools"][0]["function"]["name"] == "run_sql"
    assert payload["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert payload["options"]["num_ctx"] > 4096
    assert (turn.text, turn.stop_reason) == ("Done.", "end_turn")
    assert (turn.input_tokens, turn.output_tokens) == (11, 7)


@pytest.mark.parametrize("arguments", [{"query": "SELECT 1"}, '{"query": "SELECT 1"}'])
def test_ollama_tool_calls_are_parsed(monkeypatch: pytest.MonkeyPatch, arguments: Any) -> None:
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "run_sql", "arguments": arguments}}],
    }
    FakeOllama(monkeypatch, ollama_reply(message))

    turn = OllamaLLM("small").respond("s", TOOLS, [])

    assert turn.stop_reason == "tool_use"
    assert turn.tool_calls == [ToolCall("call-0", "run_sql", {"query": "SELECT 1"})]


def test_ollama_length_stop_is_not_treated_as_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = ollama_reply({"role": "assistant", "content": "cut"}, done_reason="length")
    FakeOllama(monkeypatch, reply)

    assert OllamaLLM("small").respond("s", TOOLS, []).stop_reason == "max_tokens"


def test_ollama_continuation_returns_each_tool_result() -> None:
    raw = {"role": "assistant", "content": ""}
    turn = Turn("", [CALL], "tool_use", 0, 0, raw)

    messages = OllamaLLM("small").continuation(turn, [ToolResult(CALL, "rows", False)])

    assert messages == [raw, {"role": "tool", "tool_name": "run_sql", "content": "rows"}]


def test_ollama_extract_requests_the_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = ollama_reply({"role": "assistant", "content": '{"number": 74}'})
    fake = FakeOllama(monkeypatch, reply)

    facts, input_tokens, output_tokens = OllamaLLM("small").extract("read this", Facts)

    assert facts.number == 74
    assert (input_tokens, output_tokens) == (11, 7)
    assert fake.payloads[0]["format"]["properties"]["number"]["type"] == "integer"


def test_ollama_bad_structured_output_fails_only_that_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = ollama_reply({"role": "assistant", "content": '{"number": "many"}'})
    FakeOllama(monkeypatch, reply)

    with pytest.raises(LLMError):
        OllamaLLM("small").extract("read this", Facts)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (http_error(404, b"model not found"), LLMFatalError),
        (http_error(400, b"does not support tools"), LLMFatalError),
        (http_error(500, b"server error"), LLMError),
        (urllib.error.URLError(ConnectionRefusedError("refused")), LLMFatalError),
        (urllib.error.URLError(TimeoutError("slow")), LLMError),
        (TimeoutError("slow"), LLMError),
    ],
)
def test_ollama_errors_are_classified(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: type[Exception]
) -> None:
    FakeOllama(monkeypatch, error)

    with pytest.raises(expected):
        OllamaLLM("small").respond("s", TOOLS, [])


class FakeAnthropic:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.kwargs: dict[str, Any] = {}
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    parse = create


def anthropic_reply(*content: Any, stop_reason: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=3, output_tokens=2)
    return SimpleNamespace(content=list(content), stop_reason=stop_reason, usage=usage)


def test_anthropic_turn_keeps_blocks_for_replay() -> None:
    blocks = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=" Checking. "),
        SimpleNamespace(type="tool_use", id="id-1", name="run_sql", input={"query": "SELECT 1"}),
    ]
    client = FakeAnthropic(anthropic_reply(*blocks, stop_reason="tool_use"))

    llm = AnthropicLLM(client)
    turn = llm.respond("s", TOOLS, [{"role": "user", "content": "hi"}])
    messages = llm.continuation(turn, [ToolResult(CALL, "rows", True)])

    assert client.kwargs["output_config"] == {"effort": "high"}
    assert turn.text == "Checking."
    assert turn.tool_calls == [CALL]
    assert messages[0] == {"role": "assistant", "content": blocks}
    assert messages[1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "id-1",
        "content": "rows",
        "is_error": True,
    }


def test_anthropic_extract_uses_the_schema() -> None:
    reply = anthropic_reply()
    reply.parsed_output = Facts(number=74)
    client = FakeAnthropic(reply)

    facts, input_tokens, output_tokens = AnthropicLLM(client).extract("read this", Facts)

    assert facts.number == 74
    assert (input_tokens, output_tokens) == (3, 2)
    assert client.kwargs["output_format"] is Facts


REQUEST = httpx2.Request("POST", "https://api.example.test")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            anthropic.BadRequestError(
                "low credit", response=httpx2.Response(400, request=REQUEST), body=None
            ),
            LLMFatalError,
        ),
        (
            anthropic.AuthenticationError(
                "bad key", response=httpx2.Response(401, request=REQUEST), body=None
            ),
            LLMFatalError,
        ),
        (
            anthropic.PermissionDeniedError(
                "denied", response=httpx2.Response(403, request=REQUEST), body=None
            ),
            LLMFatalError,
        ),
        (anthropic.APIConnectionError(request=REQUEST), LLMError),
    ],
)
def test_anthropic_errors_are_classified(error: Exception, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        AnthropicLLM(FakeAnthropic(error)).respond("s", TOOLS, [])
