"""Searching the scrollback.

xterm ships a search addon and it was never loaded, so the only way through a day's
output was to scroll. `Ctrl+F` belongs to readline, so this is on `Ctrl+Shift+F` --
the same reasoning that put the command palette on `Ctrl+Shift+P`.
"""

from __future__ import annotations

from typing import Any


def _selection(page: Any) -> str:
    return str(
        page.evaluate(
            """() => { const a = Alpine.$data(document.querySelector('[x-data]'));
                const t = a.tabs.find(t => t.id === a.activeTabId);
                return t?._term?.getSelection() || ''; }"""
        )
    )


def _open_session(page: Any) -> None:
    page.locator(".fz-srv-item", has_text="prod-web-01").first.get_by_role(
        "button", name="SSH", exact=True
    ).click()
    page.wait_for_selector(".xterm-viewport", timeout=30_000)
    page.wait_for_timeout(2500)
    # Something to find, far enough back that scrolling to it would be work.
    page.keyboard.type("printf 'NEEDLE-%s\\n' HERE; for i in $(seq 1 60); do echo pad; done\n")
    page.wait_for_timeout(2500)


def test_the_search_bar_opens_on_ctrl_shift_f(page: Any, lab: dict[str, Any]) -> None:
    _open_session(page)
    page.keyboard.press("Control+Shift+F")
    page.wait_for_selector(".fz-find", state="visible", timeout=10_000)
    assert page.evaluate("() => document.activeElement.type") == "search", (
        "the search box did not take the focus"
    )


def test_it_finds_something_scrolled_out_of_sight(page: Any, lab: dict[str, Any]) -> None:
    _open_session(page)
    page.keyboard.press("Control+Shift+F")
    page.wait_for_selector(".fz-find", state="visible", timeout=10_000)
    page.keyboard.type("NEEDLE-HERE")
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    assert "NEEDLE-HERE" in _selection(page), "the match was not selected"


def test_a_miss_says_so_rather_than_doing_nothing(page: Any, lab: dict[str, Any]) -> None:
    """A search box that reacts to nothing is indistinguishable from a broken one."""
    _open_session(page)
    page.keyboard.press("Control+Shift+F")
    page.wait_for_selector(".fz-find", state="visible", timeout=10_000)
    page.keyboard.type("zzz-not-in-this-scrollback")
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    assert page.locator(".fz-find .hint", has_text="No match").is_visible()
    assert page.locator(".fz-find input.miss").count() == 1


def test_escape_closes_it_and_gives_the_terminal_back(page: Any, lab: dict[str, Any]) -> None:
    """Closing a search box and then finding you cannot type is the focus bug again."""
    _open_session(page)
    page.keyboard.press("Control+Shift+F")
    page.wait_for_selector(".fz-find", state="visible", timeout=10_000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    assert not page.locator(".fz-find").is_visible()

    page.keyboard.type("printf 'AFTER%s\\n' FIND\n")
    page.wait_for_timeout(2000)
    assert "AFTERFIND" in page.locator(".xterm-rows").last.inner_text()
