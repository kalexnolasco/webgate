"""Scrollbars, which the application styles twice over.

Since Chromium 121, an element that has `scrollbar-color` or `scrollbar-width` has
its `::-webkit-scrollbar` rules ignored. The stylesheet set both -- the standard
property on `*`, the pseudo-elements globally -- so every scrolling surface in the
application quietly fell back to the 15px native bar with arrow buttons. It showed
up worst down the side of a terminal with no history to scroll.

Headless Chromium uses overlay scrollbars, which take no layout space, so the width
is only measurable in a headed run (`--headed`). The conflict itself is measurable
either way, and it is the actual defect.
"""

from __future__ import annotations

from typing import Any

import pytest


def _supports_pseudo(page: Any) -> bool:
    return bool(page.evaluate("() => CSS.supports('selector(::-webkit-scrollbar)')"))


def test_no_element_gets_both_ways_of_styling_a_scrollbar(page: Any) -> None:
    """The defect, stated as the invariant that was broken.

    A browser with `::-webkit-scrollbar` must not meet `scrollbar-color` or
    `scrollbar-width` anywhere, because the one cancels the other.
    """
    if not _supports_pseudo(page):
        pytest.skip("this engine has no ::-webkit-scrollbar to be cancelled")

    offenders = page.evaluate(
        """() => [...document.querySelectorAll('*')].map(el => {
            const s = getComputedStyle(el);
            return (s.scrollbarColor !== 'auto' || s.scrollbarWidth !== 'auto')
                ? `${el.tagName.toLowerCase()}.${el.className || '-'}`
                  + ` (color=${s.scrollbarColor}, width=${s.scrollbarWidth})`
                : null;
        }).filter(Boolean).slice(0, 8)"""
    )
    assert offenders == [], f"these elements cancel their own scrollbar styling: {offenders}"


def test_a_fresh_terminal_reserves_ten_pixels_not_fifteen(page: Any, lab: dict[str, Any]) -> None:
    """The visible consequence, on the surface it was reported against.

    xterm gives its viewport `overflow-y: scroll`, so the bar is reserved whether or
    not there is any history -- which is why a session with nothing in it showed a
    native scrollbar with arrow buttons down its right-hand side.
    """
    page.locator(".fz-srv-item", has_text="prod-web-01").first.get_by_role(
        "button", name="SSH", exact=True
    ).click()
    page.wait_for_selector(".xterm-viewport", timeout=30_000)
    page.wait_for_timeout(2000)

    state = page.evaluate(
        """() => { const v = document.querySelector('.xterm-viewport');
            return { reserved: v.offsetWidth - v.clientWidth,
                     overflow: getComputedStyle(v).overflowY,
                     scrollable: v.scrollHeight > v.clientHeight }; }"""
    )
    assert state["overflow"] == "scroll", "xterm no longer reserves the bar; retarget this"
    assert not state["scrollable"], "the session already has history; the test proves less"
    if state["reserved"] == 0:
        pytest.skip("overlay scrollbars take no layout space; run with WEBGATE_E2E_HEADED=1")
    assert state["reserved"] == 10, f"the native scrollbar is back: {state['reserved']}px"


def test_the_fix_holds_in_the_light_theme(page: Any) -> None:
    """The colours come from CSS variables, so the theme button must not undo it."""
    if not _supports_pseudo(page):
        pytest.skip("this engine has no ::-webkit-scrollbar to be cancelled")
    page.get_by_role("button", name="Switch to light theme").click()
    page.wait_for_timeout(500)
    assert page.evaluate(
        """() => [...document.querySelectorAll('*')].every(el => {
            const s = getComputedStyle(el);
            return s.scrollbarColor === 'auto' && s.scrollbarWidth === 'auto';
        })"""
    ), "the light theme reintroduces the conflict"
