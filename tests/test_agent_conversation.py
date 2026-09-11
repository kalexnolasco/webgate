"""Transcript handling.

Trimming is the risky part: an OpenAI-compatible API rejects a conversation whose
`tool` replies do not follow an assistant turn that asked for them, so shrinking a
transcript must never break that pairing.
"""

import pytest

from webgate.agent.conversation import CHARS_PER_TOKEN, STUB, to_display, trim


def _tool_call(cid: str, name: str) -> dict:
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}


def _exchange(n: int, output_size: int = 200) -> list[dict]:
    """One question, one tool round, one answer."""
    return [
        {"role": "user", "content": f"question {n}"},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call(f"c{n}", "disk_usage")]},
        {"role": "tool", "tool_call_id": f"c{n}", "content": "x" * output_size},
        {"role": "assistant", "content": f"answer {n}"},
    ]


def _transcript(exchanges: int, output_size: int = 200) -> list[dict]:
    messages = [{"role": "system", "content": "system prompt"}]
    for n in range(exchanges):
        messages.extend(_exchange(n, output_size))
    return messages


def test_a_short_transcript_is_untouched():
    messages = _transcript(2)
    assert trim(messages, budget_tokens=100_000) is messages


def test_oversized_output_is_stubbed_before_anything_is_dropped():
    """A budget that stubbing alone can satisfy must not lose any messages.

    The most recent turns are protected from stubbing, so the budget has to leave
    room for them; below that, dropping is the correct fallback (covered separately).
    """
    messages = _transcript(12, output_size=4000)
    out = trim(messages, budget_tokens=6000)

    assert len(out) == len(messages), "stubbing should come before dropping"
    assert any(m.get("content") == STUB for m in out if m.get("role") == "tool")
    # The most recent exchange keeps its real output.
    assert out[-2]["content"] != STUB


def test_dropping_is_the_fallback_when_stubbing_is_not_enough():
    messages = _transcript(12, output_size=4000)
    out = trim(messages, budget_tokens=800)
    assert len(out) < len(messages)


def test_the_budget_is_always_met():
    """Overshooting a model's context is a hard failure, not a longer prompt.

    The recent window is protected from the earlier passes, so without a final
    fallback a small budget would be silently ignored.
    """
    import json

    messages = _transcript(12, output_size=4000)
    for budget in (6000, 4000, 2000, 800, 400):
        out = trim(messages, budget_tokens=budget)
        size = sum(len(json.dumps(m)) for m in out) // CHARS_PER_TOKEN
        assert size <= budget, f"budget {budget} overshot at {size}"


def test_the_system_prompt_always_survives():
    out = trim(_transcript(40, output_size=4000), budget_tokens=1000)
    assert out[0]["role"] == "system"
    assert out[0]["content"] == "system prompt"


def test_the_opening_question_survives():
    """Losing it would leave the model without the host it is investigating."""
    out = trim(_transcript(40, output_size=4000), budget_tokens=1000)
    assert out[1] == {"role": "user", "content": "question 0"}


def test_tool_replies_never_outlive_their_assistant_turn():
    """An orphaned `tool` message is a 400 from the provider, not a smaller prompt."""
    out = trim(_transcript(40, output_size=6000), budget_tokens=800)

    open_calls: set[str] = set()
    for message in out:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                open_calls.add(call["id"])
        elif message.get("role") == "tool":
            assert message["tool_call_id"] in open_calls, "tool reply without its request"


def test_recent_turns_are_kept_whole():
    out = trim(_transcript(40, output_size=4000), budget_tokens=1000)
    assert out[-1]["content"] == "answer 39"


def test_trimming_does_not_mutate_the_original():
    messages = _transcript(8, output_size=4000)
    before = messages[2]["content"]
    trim(messages, budget_tokens=500)
    assert messages[2]["content"] == before


def test_display_hides_the_system_prompt_and_pairs_commands():
    turns = to_display(_transcript(2))
    assert [t["role"] for t in turns] == ["user", "agent", "user", "agent"]
    assert turns[0]["text"] == "question 0"
    assert turns[1]["text"] == "answer 0"
    # The commands run to produce an answer are attributed to that answer.
    assert turns[1]["commands"] == ["disk_usage"]


def test_display_of_an_empty_transcript():
    assert to_display([]) == []
    assert to_display([{"role": "system", "content": "x"}]) == []


@pytest.mark.asyncio
async def test_conversation_survives_a_reload(client, auth_headers, db_session):
    """It lives in the database precisely so another worker can pick it up."""
    from webgate.agent import conversation

    await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "ollama"},
    )
    messages = _transcript(1)
    await conversation.save(db_session, 1, 42, messages)
    assert await conversation.load(db_session, 1, 42) == messages

    await conversation.clear(db_session, 1, 42)
    assert await conversation.load(db_session, 1, 42) == []


@pytest.mark.asyncio
async def test_conversations_are_per_user_and_per_server(db_session):
    from webgate.agent import conversation

    await conversation.save(db_session, 1, 10, [{"role": "user", "content": "mine"}])
    await conversation.save(db_session, 2, 10, [{"role": "user", "content": "theirs"}])

    assert (await conversation.load(db_session, 1, 10))[0]["content"] == "mine"
    assert (await conversation.load(db_session, 2, 10))[0]["content"] == "theirs"
    assert await conversation.load(db_session, 1, 11) == []


@pytest.mark.asyncio
async def test_chat_endpoints_respect_the_server_opt_in(client, auth_headers):
    await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "ollama"},
    )
    srv = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "no-agent", "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    sid = srv.json()["id"]
    assert (await client.get(f"/api/agent/chat/{sid}", headers=auth_headers)).status_code == 403

    await client.put(f"/api/servers/{sid}", headers=auth_headers, json={"agent_enabled": True})
    resp = await client.get(f"/api/agent/chat/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"server": "no-agent", "turns": [], "exchanges": 0}


def test_the_host_preamble_is_not_shown_as_the_users_words():
    """The opening message carries host details the server composed, not the question."""
    turns = to_display(
        [
            {"role": "system", "content": "sp"},
            {
                "role": "user",
                "content": (
                    "Host: prod-web-01 (deploy@10.0.0.5:22)\nDescription: none\n\nWhy is it slow?"
                ),
            },
            {"role": "assistant", "content": "answer"},
        ]
    )
    assert turns[0]["text"] == "Why is it slow?"
    assert "Host:" not in turns[0]["text"]
