"""Optional live questions. Off unless started with `make live`.

The app works without this module and never imports it for normal use. A stray API key must not
quietly open a paid endpoint, so LIVE_MODE has to be switched on as well.
"""

import os
import threading
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field

from phenoctx.agents import build_agents, open_read_only, run_once
from phenoctx.db import DEFAULT_CSV_DIR
from phenoctx.decode import Candidate, Decoding, build_candidates, decode_run
from phenoctx.llm import LLM, select_llm


class LiveStatus(BaseModel):
    enabled: bool
    backend: str | None = None
    model: str | None = None


class LiveQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    agent: Literal["naive", "context"]


class LiveAnswer(BaseModel):
    answer: str | None
    steps: list[dict[str, Any]]
    error: str | None
    used_tools: bool
    decoding: Decoding


def live_llm(env: Mapping[str, str]) -> LLM | None:
    """Return the model for live questions, or None if live mode is off or can't work.

    Live mode needs the full CSVs, for the same reason the agents refuse the extract. It defaults
    to the local model, so `make live` works without any other settings.
    """
    if env.get("LIVE_MODE", "").strip().lower() != "on":
        return None
    if not all((DEFAULT_CSV_DIR / f"{t}.csv").is_file() for t in ("patients", "conditions")):
        return None
    settings = dict(env)
    if not settings.get("ANTHROPIC_API_KEY") and not settings.get("OLLAMA_MODEL"):
        settings.setdefault("AGENT_BACKEND", "ollama")
    return select_llm(settings)


def status(env: Mapping[str, str] = os.environ) -> LiveStatus:
    llm = live_llm(env)
    if llm is None:
        return LiveStatus(enabled=False)
    return LiveStatus(enabled=True, backend=llm.backend, model=llm.model)


@lru_cache(maxsize=1)
def _data() -> tuple[duckdb.DuckDBPyConnection, list[Candidate]]:
    con = open_read_only()
    return con, build_candidates(con)


# A local model handles one request at a time, and this keeps a second click from queuing work.
_one_at_a_time = threading.Lock()


def ask(request: LiveQuestion, env: Mapping[str, str] = os.environ) -> LiveAnswer | None:
    """Answer one question, or return None when live mode is off."""
    llm = live_llm(env)
    if llm is None:
        return None
    with _one_at_a_time:
        con, candidates = _data()
        agent = next(a for a in build_agents(con) if a.name == request.agent)
        run = run_once(llm, con, agent, 1, question=request.question, score=False)
    return LiveAnswer(
        answer=run["answer"],
        steps=run["steps"],
        error=run["error"],
        used_tools=run["tool_calls"] > 0,
        decoding=decode_run(con, run["steps"], run["answer"], candidates),
    )
