"""Recall of past findings.

Keyword search, plus the visibility rule that keeps one
team's production output away from another's.
"""

import pytest

from webgate.agent import memory


async def _finding(session, **kw):
    defaults = {
        "server_id": 1,
        "server_name": "prod-web-01",
        "user_id": 1,
        "username": "alice",
        "question": "why is it slow",
        "answer": "The disk was full.",
        "tools": ["disk_usage"],
        "model": "m",
    }
    return await memory.record(session, **{**defaults, **kw})


# ------------------------------------------------------------------------- keywords


@pytest.mark.asyncio
async def test_keyword_search_finds_by_answer(db_session):
    await _finding(db_session, answer="The nginx unit had crashed with an OOM kill.")
    hits = await memory.search_keywords(db_session, "oom", user_id=1, server_ids=None)
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_keyword_search_requires_every_word(db_session):
    await _finding(db_session, answer="The disk was full.")
    assert await memory.search_keywords(db_session, "disk full", user_id=1, server_ids=None)
    assert not await memory.search_keywords(
        db_session, "disk memory", user_id=1, server_ids=None
    )


@pytest.mark.asyncio
async def test_keyword_search_is_case_insensitive(db_session):
    await _finding(db_session, answer="Postgres refused connections.")
    assert await memory.search_keywords(db_session, "POSTGRES", user_id=1, server_ids=None)


@pytest.mark.asyncio
async def test_keyword_search_can_be_scoped_to_one_server(db_session):
    await _finding(db_session, server_id=1, answer="disk full here")
    await _finding(db_session, server_id=2, answer="disk full there")
    hits = await memory.search_keywords(
        db_session, "disk", user_id=1, server_ids=None, server_id=2
    )
    assert len(hits) == 1
    assert hits[0].server_id == 2


# ---------------------------------------------------------------------- visibility


@pytest.mark.asyncio
async def test_a_user_does_not_see_another_users_findings(db_session):
    await _finding(db_session, user_id=2, server_id=99, answer="secret production detail")
    # user 1 reaches no servers and owns nothing
    assert not await memory.search_keywords(db_session, "secret", user_id=1, server_ids=[])


@pytest.mark.asyncio
async def test_a_user_sees_findings_for_servers_they_can_reach(db_session):
    await _finding(db_session, user_id=2, server_id=7, answer="shared production detail")
    hits = await memory.search_keywords(db_session, "shared", user_id=1, server_ids=[7])
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_an_admin_sees_everything(db_session):
    await _finding(db_session, user_id=2, server_id=99, answer="anything")
    hits = await memory.search_keywords(db_session, "anything", user_id=1, server_ids=None)
    assert len(hits) == 1


# ----------------------------------------------------------------------- retention


@pytest.mark.asyncio
async def test_forget_removes_your_own_finding(db_session):
    finding = await _finding(db_session, user_id=1)
    assert await memory.forget(db_session, finding.id, user_id=1, is_admin=False)
    assert not await memory.recent(db_session, user_id=1, server_ids=None)


@pytest.mark.asyncio
async def test_forget_refuses_someone_elses_finding(db_session):
    finding = await _finding(db_session, user_id=2)
    assert not await memory.forget(db_session, finding.id, user_id=1, is_admin=False)


@pytest.mark.asyncio
async def test_an_admin_can_forget_any_finding(db_session):
    finding = await _finding(db_session, user_id=2)
    assert await memory.forget(db_session, finding.id, user_id=1, is_admin=True)


@pytest.mark.asyncio
async def test_a_zero_retention_window_keeps_everything(db_session):
    await _finding(db_session)
    assert await memory.purge_older_than(db_session, 0) == 0
    assert len(await memory.recent(db_session, user_id=1, server_ids=None)) == 1


@pytest.mark.asyncio
async def test_recent_findings_are_returned_newest_first(db_session):
    await _finding(db_session, answer="older")
    await _finding(db_session, answer="newer")
    rows = await memory.recent(db_session, user_id=1, server_ids=None)
    assert rows[0].answer == "newer"


@pytest.mark.asyncio
async def test_to_dict_shapes_a_finding_for_the_client(db_session):
    finding = await _finding(db_session)
    payload = memory.to_dict(finding)
    assert payload["tools"] == ["disk_usage"]
    assert "answer" in payload
