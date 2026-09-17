"""Resize frames, which until v2.8.1 nothing had ever sent.

The terminal panel lost its `display: flex` the first time Alpine showed it, so it
never became a flex item, never re-fitted, and never resized. A whole path -- the
browser sending `{"type": "resize"}`, the gateway passing it to the SSH channel --
had therefore never run outside a unit test, and it was written as if it could not
fail: the `await ssh.resize(...)` sat inside a `try` narrow enough that anything
other than a parse error escaped to an outer `except Exception` that ended the input
loop. One failed resize took the session with it, silently.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect

from webgate.terminal.ws_handler import _client_input_loop, _resize_of

# ------------------------------------------------------- telling the two apart


def test_a_resize_frame_is_recognised():
    assert _resize_of('{"type": "resize", "cols": 198, "rows": 51}') == (198, 51)


@pytest.mark.parametrize(
    "message",
    [
        "ls -la\r",
        "",
        "{",
        '{"cols": 80, "rows": 24}',  # the opening frame, not a resize
        '["resize", 80, 24]',
        '"resize"',
        "42",
    ],
)
def test_terminal_input_is_not_mistaken_for_one(message: str):
    assert _resize_of(message) is None


@pytest.mark.parametrize(
    "message",
    ['{"type": "resize", "cols": "wide", "rows": 24}', '{"type": "resize"}'],
)
def test_a_malformed_resize_is_still_a_resize(message: str):
    """It must be swallowed, not fallen through to -- otherwise a control frame
    would be typed into somebody's shell as keystrokes."""
    assert _resize_of(message) == (0, 0)


# ------------------------------------------------------------- the input loop


def _loop_over(messages: list[str]):
    """A websocket that hands out `messages` and then disconnects."""
    queue = list(messages)

    async def receive_text() -> str:
        if not queue:
            raise WebSocketDisconnect(1000)
        return queue.pop(0)

    ws = MagicMock()
    ws.receive_text = receive_text
    return ws


@pytest.mark.asyncio
async def test_a_resize_that_fails_does_not_end_the_session():
    """The defect: this used to break the loop and drop the connection."""
    ssh = MagicMock()
    ssh.resize = AsyncMock(side_effect=OSError("channel is closed"))
    sess = MagicMock()
    sess.write_input = AsyncMock()

    await _client_input_loop(
        _loop_over(['{"type": "resize", "cols": 198, "rows": 51}', "whoami\r"]), ssh, sess, "admin"
    )

    sess.write_input.assert_awaited_once_with("whoami\r", "admin")


@pytest.mark.asyncio
async def test_a_resize_to_nothing_is_not_passed_on():
    """A hidden pane measures zero. There is no terminal with no rows."""
    ssh = MagicMock()
    ssh.resize = AsyncMock()
    sess = MagicMock()
    sess.write_input = AsyncMock()

    await _client_input_loop(
        _loop_over(['{"type": "resize", "cols": 0, "rows": 0}']), ssh, sess, "admin"
    )

    ssh.resize.assert_not_awaited()
    sess.write_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_good_resize_reaches_the_channel_and_nothing_else():
    ssh = MagicMock()
    ssh.resize = AsyncMock()
    sess = MagicMock()
    sess.write_input = AsyncMock()

    await _client_input_loop(
        _loop_over(['{"type": "resize", "cols": 198, "rows": 51}']), ssh, sess, "admin"
    )

    ssh.resize.assert_awaited_once_with(198, 51)
    sess.write_input.assert_not_awaited()
