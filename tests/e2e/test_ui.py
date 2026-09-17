"""What the browser actually does.

The unit suite proves an endpoint writes an audit entry. Only this proves that
deleting a file in the file browser puts that file's name in the audit panel -- which
is what a user reported missing, and which no API test would have caught, because the
API was never the part that was wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

LAB_SERVER = "prod-web-01"
LAB_FILE = "nginx.conf"


def _card(page: Any, name: str) -> Any:
    """The server's row in the Site Manager."""
    return page.locator(".fz-srv-item", has_text=name).first


def _modal(page: Any) -> Any:
    """The modal on screen.

    Every modal is in the DOM at all times and only hidden with `x-show`, so an
    unscoped `.fz-modal` returns whichever happens to be first in the markup.
    """
    return page.locator(".fz-modal:visible").first


def _open_sftp(page: Any, name: str = LAB_SERVER, path: str | None = None) -> None:
    """Open the file browser, and go somewhere with files in it.

    The browser opens at `/`, which on the lab host is the machine's real root. The
    fixture files live elsewhere, so the test navigates rather than assuming.
    """
    _card(page, name).get_by_role("button", name="SFTP").click()
    # The table element appears as soon as the tab renders, while the listing for `/`
    # is still in flight. Navigating before it lands gets clobbered when it does, so
    # wait for rows, not for the container.
    page.wait_for_selector(".fz-filelist tbody tr >> nth=3", timeout=30_000)
    if path:
        page.fill(".path-input", path)
        page.press(".path-input", "Enter")
        page.wait_for_selector(f".fz-filelist >> text={LAB_FILE}", timeout=20_000)


def _open_ssh(page: Any, name: str = LAB_SERVER) -> None:
    _card(page, name).get_by_role("button", name="SSH", exact=True).click()
    page.wait_for_selector(".fz-snip", timeout=30_000)


def _admin_menu(page: Any, item: str) -> None:
    page.get_by_role("button", name="Admin").click()
    page.get_by_role("menuitem", name=item).click()


def _search_audit(page: Any, term: str) -> Any:
    _admin_menu(page, "Audit log")
    page.wait_for_selector(".fz-audit-filters", timeout=15_000)
    page.fill(".fz-audit-filters input[type=search]", term)
    page.wait_for_timeout(900)
    return _modal(page).locator("table tbody tr")


# ------------------------------------------------------------------ the reported bug


def test_deleting_a_file_puts_its_name_in_the_audit_log(page: Any, lab: dict[str, Any]) -> None:
    """Reported: "they deleted a file and we do not know which one"."""
    target = lab["files"] / "old-backup.tar.gz"
    assert target.exists(), "the fixture file is missing before we start"

    _open_sftp(page, path=str(lab["files"]))
    page.get_by_label("Select old-backup.tar.gz").check()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".fz-batchbar").get_by_role("button", name="Delete").click()
    page.wait_for_timeout(2000)

    assert not target.exists(), "the file was never actually deleted on the host"

    rows = _search_audit(page, "old-backup")
    assert rows.count() >= 1, "nothing in the audit log names the deleted file"
    entry = rows.first.inner_text()
    assert "old-backup.tar.gz" in entry
    assert "sftp_delete" in entry
    assert LAB_SERVER in entry, "the entry does not say which server"
    assert "admin" in entry, "the entry does not say who"


def test_an_empty_search_says_so_instead_of_looking_broken(page: Any) -> None:
    _search_audit(page, "zzz-nothing-matches-this")
    assert page.locator(".fz-audit-empty").is_visible()
    assert "Nothing matches" in page.inner_text(".fz-audit-empty")


def test_the_action_filter_offers_only_what_happened(page: Any) -> None:
    """Rather than a name to guess at."""
    _admin_menu(page, "Audit log")
    page.wait_for_selector(".fz-audit-filters", timeout=15_000)
    options = page.locator(".fz-audit-filters select option").all_inner_texts()
    assert "login" in options
    assert "server_created" in options


# ------------------------------------------------------------------------- the basics


def test_the_site_manager_lists_the_fleet(page: Any) -> None:
    page.wait_for_selector(".fz-serverlist", timeout=15_000)
    listed = page.inner_text(".fz-serverlist")
    for name in [LAB_SERVER, "prod-db-primary", "staging-app-01", "edge-cdn-lhr"]:
        assert name in listed


def test_the_command_palette_jumps_to_a_server(page: Any) -> None:
    page.keyboard.press("Control+Shift+P")
    page.wait_for_selector(".fz-pal-item", timeout=10_000)
    page.fill(".fz-palette-field input", "cache")
    page.wait_for_timeout(500)
    assert "prod-cache-01" in page.locator(".fz-pal-item").first.inner_text()


def test_the_settings_panel_says_where_each_value_comes_from(page: Any) -> None:
    _admin_menu(page, "Settings")
    page.wait_for_selector(".fz-setting", timeout=15_000)
    body = _modal(page).inner_text()
    assert "Verify SSH host keys" in body
    assert "default" in body  # the source badge
    assert page.locator(".fz-setting-warn").first.is_visible(), "the risky setting is unmarked"


def test_shared_snippets_are_marked_and_the_dangerous_one_is_flagged(page: Any) -> None:
    _open_ssh(page)
    toolbar = page.locator(".fz-snip")
    names = toolbar.all_inner_texts()
    assert any("Disk usage" in n for n in names)
    assert any("Restart nginx" in n for n in names)
    assert page.locator(".fz-snip-shared").count() >= 3, "shared snippets are not marked"
    assert any(n.strip().startswith("!") for n in names), "the confirm snippet is not flagged"


def test_a_real_ssh_session_opens(page: Any) -> None:
    """Through the WebSocket, to the lab host, with a live shell behind it."""
    _open_ssh(page)
    page.wait_for_timeout(4000)
    assert "Disconnected" not in page.inner_text(".fz-connbar, body")


# ------------------------------------------------------------ the docs come from here


@pytest.mark.docs
def test_capture_the_documentation_screenshots(page: Any, shot: Any, lab: dict[str, Any]) -> None:
    """The screenshots in the docs are taken from the build these tests just drove,
    so they cannot drift into showing an interface that no longer exists."""
    page.wait_for_selector(".fz-serverlist", timeout=15_000)
    page.wait_for_timeout(800)
    assert Path(shot("site-manager")).exists()

    _admin_menu(page, "Settings")
    page.wait_for_selector(".fz-setting", timeout=15_000)
    page.wait_for_timeout(500)
    shot("settings")
    page.keyboard.press("Escape")

    _admin_menu(page, "Audit log")
    page.wait_for_selector(".fz-audit-filters", timeout=15_000)
    page.wait_for_timeout(500)
    shot("audit")
    page.keyboard.press("Escape")

    page.keyboard.press("Control+Shift+P")
    page.wait_for_selector(".fz-pal-item", timeout=10_000)
    page.fill(".fz-palette-field input", "prod")
    page.wait_for_timeout(500)
    shot("palette")
    page.keyboard.press("Escape")

    # The root of the lab host, not the sparse fixture directory: a screenshot of
    # two files in a pytest temp path shows nothing about the file browser.
    _open_sftp(page)
    page.wait_for_selector(".fz-filelist tbody tr >> nth=5", timeout=20_000)
    page.wait_for_timeout(800)
    shot("sftp")

    # The editor, on a file that has something to highlight. The SFTP tab is already
    # open on the host's root, so this walks it over rather than opening a second one.
    page.fill(".path-input", str(lab["files"]))
    page.press(".path-input", "Enter")
    page.wait_for_selector(".fz-filelist >> text=deploy.py", timeout=20_000)
    page.locator(".fz-filelist tbody tr", has_text="deploy.py").first.dblclick()
    page.wait_for_selector(".fz-lang", timeout=20_000)
    page.wait_for_timeout(1000)
    shot("editor")


# --------------------------------------------------------------- keyboard focus


def _type_into_terminal(page: Any, marker: str) -> None:
    """Type at the page, never at the terminal.

    `page.keyboard` goes to whatever holds the focus, which is the whole point: if
    nothing focused the terminal, these keystrokes land on <body> and vanish. The
    command is built so its output differs from its own echo -- `FOCUS%s` on screen
    is the shell repeating what was typed, `FOCUSx` is the shell having run it.
    """
    page.keyboard.type(f"printf 'FOCUS%s\\n' {marker}\n")


def _terminal_text(page: Any) -> str:
    return str(page.locator(".xterm-rows").last.inner_text())


def _wait_for_shell(page: Any) -> None:
    page.wait_for_selector(".xterm-rows", timeout=30_000)
    page.wait_for_timeout(3000)


def test_a_terminal_takes_typing_without_being_clicked_first(
    page: Any, lab: dict[str, Any]
) -> None:
    """The reported bug.

    The session connected, the remote prompt was painted, and every keystroke went
    nowhere: xterm reads from a hidden textarea and nothing in the frontend ever
    called focus(), so the terminal was deaf until the user clicked into it.
    """
    _open_ssh(page)
    _wait_for_shell(page)
    _type_into_terminal(page, "a")
    page.wait_for_timeout(2000)
    assert "FOCUSa" in _terminal_text(page), "the terminal never received the keystrokes"


def test_coming_back_to_a_terminal_tab_takes_typing_again(page: Any, lab: dict[str, Any]) -> None:
    """Leaving for the Site Manager and returning used to need another click."""
    _open_ssh(page)
    _wait_for_shell(page)
    page.get_by_role("tab", name="Site Manager").click()
    page.wait_for_selector(".fz-serverlist", timeout=15_000)
    page.locator(".fz-tab", has_text=LAB_SERVER).first.click()
    page.wait_for_timeout(1000)
    _type_into_terminal(page, "b")
    page.wait_for_timeout(2000)
    assert "FOCUSb" in _terminal_text(page), "the terminal was deaf after switching back"


def test_a_split_tab_takes_typing_too(page: Any, lab: dict[str, Any]) -> None:
    """A split carries a terminal in a differently-named container; it was missed
    by every focus and re-fit path the tab strip had."""
    _card(page, LAB_SERVER).get_by_role("button", name="Split").click()
    _wait_for_shell(page)
    _type_into_terminal(page, "c")
    page.wait_for_timeout(2000)
    assert "FOCUSc" in _terminal_text(page), "the split's terminal never got the focus"


def test_a_reconnect_does_not_pull_the_caret_out_of_quick_connect(
    page: Any, lab: dict[str, Any]
) -> None:
    """Focus the user did not ask for must not take the keyboard away from them.

    The socket is dropped from the page, so the terminal really does reconnect and
    really does run the focus path -- while the caret is in a field being typed in.
    """
    _open_ssh(page)
    _wait_for_shell(page)
    page.get_by_title("Quick connect (Ctrl+K)").click()
    page.click("#qc-host")
    page.type("#qc-host", "somewhere.internal")

    page.evaluate(
        "() => { const a = Alpine.$data(document.querySelector('[x-data]'));"
        " a.tabs.find(t => t.id === a.activeTabId)._ws.close(); }"
    )
    page.wait_for_function(
        "() => document.querySelector('.xterm-rows')?.innerText.includes('Reconnected')",
        timeout=30_000,
    )
    page.wait_for_timeout(500)

    assert page.evaluate("() => document.activeElement.id") == "qc-host"
    page.keyboard.type("!")
    assert page.input_value("#qc-host") == "somewhere.internal!"


# ------------------------------------------------------------------ file types


def _open_in_editor(page: Any, lab: dict[str, Any], name: str) -> None:
    _open_sftp(page, path=str(lab["files"]))
    page.locator(".fz-filelist tbody tr", has_text=name).first.dblclick()
    page.wait_for_selector(".fz-editor-bar", timeout=20_000)


def test_the_editor_highlights_by_file_type(page: Any, lab: dict[str, Any]) -> None:
    """The editor had no language extension at all, so every file -- a Python
    script, an nginx config, a log -- was the same undifferentiated grey."""
    _open_in_editor(page, lab, "deploy.py")
    page.wait_for_selector(".fz-lang", timeout=20_000)
    assert page.inner_text(".fz-lang").strip().lower() == "python"
    assert "import" in page.inner_text(".cm-content")
    # basicSetup highlights through style-mod, whose class names are generated, so
    # there is no stable `.tok-keyword` to look for. What is stable is the effect:
    # with a grammar loaded the line is split into spans that are not all the same
    # colour as the body text, and without one it is a single run of plain text.
    page.wait_for_function(_COLOURED_TOKENS, timeout=20_000)


def test_a_script_with_no_extension_is_read_from_its_shebang(
    page: Any, lab: dict[str, Any]
) -> None:
    """`/usr/local/bin/healthcheck` has nothing in its name to go on. The shebang
    is the only thing that says what it is, and it is right there in the file."""
    _open_in_editor(page, lab, "healthcheck")
    page.wait_for_selector(".fz-lang", timeout=20_000)
    assert page.inner_text(".fz-lang").strip().lower() == "shell"


def test_a_binary_is_refused_instead_of_offering_to_save_over_it(
    page: Any, lab: dict[str, Any]
) -> None:
    """The data loss: a binary opened as U+FFFD with a Save button next to it, and
    pressing it rewrote the file as mangled text."""
    _open_in_editor(page, lab, "service.db")
    page.wait_for_selector(".fz-editor-notice", timeout=20_000)
    notice = page.inner_text(".fz-editor-notice")
    assert "binary" in notice.lower(), notice
    assert page.get_by_role("button", name="Save").count() == 0, "Save is still offered"
    assert page.get_by_role("button", name="Download").is_visible()


def test_the_editor_follows_the_light_theme(page: Any, lab: dict[str, Any]) -> None:
    """oneDark was hardcoded, so the light interface had a black rectangle in it."""
    _open_in_editor(page, lab, "nginx.conf")
    page.wait_for_selector(".cm-editor", timeout=20_000)

    def editor_is_dark() -> bool:
        # Whatever the viewer actually sees behind the text: the editor's own
        # background when a theme paints one, and otherwise the app's, walking up
        # until something is opaque. Reading `.cm-editor` alone reports
        # `rgba(0,0,0,0)` for an unthemed editor, which is not "black".
        return bool(page.evaluate(_EDITOR_IS_DARK))

    assert editor_is_dark(), "the default theme is dark, so the editor should be too"
    page.get_by_role("button", name="Switch to light theme").click()
    page.wait_for_timeout(800)
    assert not editor_is_dark(), "the editor stayed dark in the light theme"


_COLOURED_TOKENS = """() => {
    const content = document.querySelector('.cm-content');
    if (!content) return false;
    const base = getComputedStyle(content).color;
    return [...content.querySelectorAll('.cm-line span')]
        .some(s => getComputedStyle(s).color !== base);
}"""

_EDITOR_IS_DARK = """() => {
    let el = document.querySelector('.cm-editor');
    while (el) {
        const parts = getComputedStyle(el).backgroundColor.match(/[\\d.]+/g);
        if (parts && (parts.length < 4 || Number(parts[3]) > 0)) {
            return (Number(parts[0]) + Number(parts[1]) + Number(parts[2])) / 3 < 110;
        }
        el = el.parentElement;
    }
    return false;
}"""
