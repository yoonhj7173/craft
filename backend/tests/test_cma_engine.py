"""CMA Dev-engine tests (D45). Pure parsers/message run in CI; live smoke is key-gated."""
from __future__ import annotations

import os
import types

import pytest

from app.services import cma
from app.services.cma import SESSION_OUTPUT_DIR
from app.services.cma_engine import _build_message


def _task(**kw):
    base = dict(input_payload=None, edge_id=None, result_markdown=None,
                continuations=None, instructions="Do X")
    base.update(kw)
    return types.SimpleNamespace(**base)


# --- _build_message ---

def test_build_message_basic():
    msg = _build_message(_task())
    assert "Do X" in msg
    assert SESSION_OUTPUT_DIR in msg          # deliverables 디렉토리 안내.
    assert "AWAITING_INPUT" in msg            # needs-input 센티넬 프로토콜.


def test_build_message_input_and_followups():
    msg = _build_message(_task(input_payload="upstream out", edge_id="e1",
                               continuations=[{"text": "more please"}]))
    assert "upstream out" in msg
    assert "delivered from an upstream agent" in msg
    assert "more please" in msg


# --- 이벤트 파서(cma.py) ---

def test_collect_reply_joins_agent_text():
    events = [
        {"type": "agent.message", "content": [{"type": "text", "text": "hello"}]},
        {"type": "span.model_request_end", "model_usage": {}},
        {"type": "agent.message", "content": [{"type": "text", "text": "world"}]},
    ]
    assert cma._collect_reply(events) == "hello\nworld"


def test_collect_tokens_sums_usage_including_cache():
    events = [
        {"type": "span.model_request_end", "model_usage": {
            "input_tokens": 100, "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 10, "output_tokens": 20}},
        {"type": "span.model_request_end", "model_usage": {"input_tokens": 5, "output_tokens": 3}},
    ]
    assert cma._collect_tokens(events) == (165, 23)


def test_terminal_idle_end_turn():
    events = [{"type": "session.status_running"},
              {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}]
    assert cma._terminal(events) == ("idle", "end_turn", [])


def test_terminal_requires_action_carries_event_ids():
    events = [{"type": "session.status_idle",
               "stop_reason": {"type": "requires_action", "event_ids": ["e1"]}}]
    assert cma._terminal(events) == ("idle", "requires_action", ["e1"])


def test_terminal_terminated_and_running():
    assert cma._terminal([{"type": "session.status_terminated"}]) == ("terminated", None, [])
    assert cma._terminal([{"type": "session.status_running"}]) is None
    assert cma._terminal([]) is None


# --- 라이브 스모크(키 필요, 토큰 비용) ---

@pytest.mark.skipif(os.getenv("CMA_LIVE") != "1", reason="needs live CMA API + ANTHROPIC_API_KEY")
def test_cma_client_round_trip_live():
    c = cma.CMAClient()
    env = agent = store = sess = None
    try:
        env = c.create_environment("craft-cmatest-env")
        store = c.create_memory_store("craft-cmatest-store", "test")
        agent = c.create_agent("craft-cmatest-agent", "claude-haiku-4-5", "Reply with one word.")
        sess, _ = c.create_session(agent, env, memory_store_id=store)
        c.send_user_message(sess, "Say PONG")
        res = c.poll_until_idle(sess, timeout_sec=120)
        assert res.status == "idle"
        assert res.tokens_in > 0 and res.tokens_out > 0
        assert "PONG" in res.reply.upper()
    finally:
        if sess:
            c.delete_session(sess)
        if agent:
            c.archive_agent(agent)
        if store:
            c._req("DELETE", f"/v1/memory_stores/{store}")
        if env:
            c._req("DELETE", f"/v1/environments/{env}")
        c.close()
