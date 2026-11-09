"""A thin wrapper so the agents can run on Anthropic or a local Ollama model.

Only the agents script uses this. The app never calls an LLM.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

ANTHROPIC_MODEL = "claude-opus-5-5"
ANTHROPIC_EFFORT = "high"
MAX_TOKENS = 16000

T = TypeVar("T", bound=BaseModel)

DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
OLLAMA_CONTEXT_TOKENS = 16384
OLLAMA_TIMEOUT_SECONDS = 600


class LLMError(Exception):
    """One request failed. The run is recorded as failed and the others continue."""


class LLMFatalError(Exception):
    """Every run would fail, such as a bad key or a missing model. The script stops."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    output: str
    is_error: bool


@dataclass(frozen=True)
class Turn:
    """One model response. `stop_reason` is end_turn, tool_use, or a backend's own reason."""

    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    input_tokens: int
    output_tokens: int
    raw: Any = field(default=None, repr=False)


class LLM(Protocol):
    backend: str
    model: str
    effort: str | None
    concurrency: int

    def respond(
        self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> Turn:
        """Return the model's next turn."""
        ...

    def continuation(self, turn: Turn, results: list[ToolResult]) -> list[dict[str, Any]]:
        """Return the messages that add `turn` and its tool results to the conversation."""
        ...

    def extract(self, prompt: str, schema: type[T]) -> tuple[T, int, int]:
        """Return structured data plus input and output token counts."""
        ...


class AnthropicLLM:
    backend = "anthropic"
    model = ANTHROPIC_MODEL
    effort = ANTHROPIC_EFFORT
    concurrency = 4

    def __init__(self, client: Any = None) -> None:
        import anthropic

        self._sdk = anthropic
        self._client = client or anthropic.Anthropic()

    def _call(self, request: Any, **kwargs: Any) -> Any:
        sdk = self._sdk
        try:
            return request(**kwargs)
        except (sdk.AuthenticationError, sdk.BadRequestError, sdk.PermissionDeniedError) as error:
            raise LLMFatalError(f"Anthropic rejected the request: {error}") from error
        except sdk.APIError as error:
            raise LLMError(f"{type(error).__name__}: {error}") from error

    def respond(
        self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> Turn:
        response = self._call(
            self._client.messages.create,
            model=self.model,
            max_tokens=MAX_TOKENS,
            output_config={"effort": self.effort},
            system=system,
            tools=tools,
            messages=messages,
        )
        blocks = response.content
        return Turn(
            text="\n".join(b.text for b in blocks if b.type == "text").strip(),
            tool_calls=[ToolCall(b.id, b.name, b.input) for b in blocks if b.type == "tool_use"],
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw=blocks,
        )

    def continuation(self, turn: Turn, results: list[ToolResult]) -> list[dict[str, Any]]:
        return [
            {"role": "assistant", "content": turn.raw},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result.call.id,
                        "content": result.output,
                        "is_error": result.is_error,
                    }
                    for result in results
                ],
            },
        ]

    def extract(self, prompt: str, schema: type[T]) -> tuple[T, int, int]:
        response = self._call(
            self._client.messages.parse,
            model=self.model,
            max_tokens=MAX_TOKENS,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        return response.parsed_output, response.usage.input_tokens, response.usage.output_tokens


class OllamaLLM:
    backend = "ollama"
    effort = None
    # A local model handles one request at a time, so parallel runs would only queue.
    concurrency = 1

    def __init__(self, model: str, host: str = DEFAULT_OLLAMA_HOST) -> None:
        self.model = model
        self._host = host.rstrip("/")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._host}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            message = f"Ollama returned {error.code} for {self.model}: {detail}"
            if error.code >= 500:
                raise LLMError(message) from error
            raise LLMFatalError(message) from error
        except TimeoutError as error:
            raise LLMError(f"Ollama timed out after {OLLAMA_TIMEOUT_SECONDS}s") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise LLMError(f"Ollama timed out after {OLLAMA_TIMEOUT_SECONDS}s") from error
            raise LLMFatalError(
                f"Couldn't reach Ollama at {self._host}: {error.reason}. Is it running?"
            ) from error

    def _chat(self, **fields: Any) -> dict[str, Any]:
        return self._post(
            {
                "model": self.model,
                "stream": False,
                # Ollama's default context is small and it truncates silently, which would cut
                # the system prompt or tool results without any error.
                "options": {"num_ctx": OLLAMA_CONTEXT_TOKENS, "num_predict": MAX_TOKENS},
                **fields,
            }
        )

    def respond(
        self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> Turn:
        response = self._chat(
            messages=[{"role": "system", "content": system}, *messages],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ],
        )
        message = response["message"]
        calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            arguments = call["function"].get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            calls.append(ToolCall(f"call-{index}", call["function"]["name"], arguments))

        stop_reason = "tool_use" if calls else "end_turn"
        if response.get("done_reason") == "length":
            stop_reason = "max_tokens"
        return Turn(
            text=(message.get("content") or "").strip(),
            tool_calls=calls,
            stop_reason=stop_reason,
            input_tokens=response.get("prompt_eval_count", 0),
            output_tokens=response.get("eval_count", 0),
            raw=message,
        )

    def continuation(self, turn: Turn, results: list[ToolResult]) -> list[dict[str, Any]]:
        return [
            turn.raw,
            *[
                {"role": "tool", "tool_name": result.call.name, "content": result.output}
                for result in results
            ],
        ]

    def extract(self, prompt: str, schema: type[T]) -> tuple[T, int, int]:
        response = self._chat(
            messages=[{"role": "user", "content": prompt}],
            format=schema.model_json_schema(),
        )
        try:
            parsed = schema.model_validate_json(response["message"]["content"])
        except ValidationError as error:
            raise LLMError(f"Ollama returned invalid structured output: {error}") from error
        return parsed, response.get("prompt_eval_count", 0), response.get("eval_count", 0)


def select_llm(env: Mapping[str, str]) -> LLM | None:
    """Choose a backend from the environment, or return None if neither is configured.

    AGENT_BACKEND picks one explicitly. Without it, ANTHROPIC_API_KEY selects Anthropic and
    OLLAMA_MODEL selects Ollama, with Anthropic winning if both are set.
    """
    choice = env.get("AGENT_BACKEND", "").strip().lower()
    if choice not in ("", "anthropic", "ollama"):
        raise LLMFatalError(f"AGENT_BACKEND must be anthropic or ollama, not {choice!r}.")

    has_key = bool(env.get("ANTHROPIC_API_KEY"))
    ollama_model = env.get("OLLAMA_MODEL", "").strip()

    if choice == "anthropic" or (not choice and has_key):
        return AnthropicLLM() if has_key else None
    if choice == "ollama" or ollama_model:
        host = env.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
        return OllamaLLM(ollama_model or DEFAULT_OLLAMA_MODEL, host)
    return None
