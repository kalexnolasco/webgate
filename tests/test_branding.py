"""Company branding.

The interesting cases are the ones a careless implementation gets wrong: an image
field left blank quietly wiping the logo, a hex value that is really a CSS payload,
and an upload big enough to bloat every backup from then on.
"""

import base64

import pytest

from webgate.branding.store import BrandingError, validate_color, validate_image

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode()
SVG = "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()


async def _plain_user(client, auth_headers):
    await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "plain", "password": "plainpass123", "allowed_groups": []},
    )
    token = (
        await client.post(
            "/api/auth/login", json={"username": "plain", "password": "plainpass123"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------------- colours


def test_a_valid_hex_colour_is_accepted():
    assert validate_color("#1A73E8", field="accent") == "#1a73e8"
    assert validate_color("#abc", field="accent") == "#abc"
    assert validate_color("", field="accent") == ""


@pytest.mark.parametrize(
    "payload",
    [
        "red",                                   # a name, not a hex value
        "#12345",                                # wrong length
        "#1a73e8; background: url(evil)",        # CSS injection through a colour
        "javascript:alert(1)",
        "var(--accent)",
        "#1a73e8/*",
    ],
)
def test_anything_that_is_not_a_hex_colour_is_refused(payload):
    with pytest.raises(BrandingError):
        validate_color(payload, field="accent")


@pytest.mark.asyncio
async def test_an_unknown_colour_key_is_refused(client, auth_headers):
    resp = await client.put(
        "/api/branding", headers=auth_headers, json={"colors": {"not_a_key": "#fff"}}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_a_css_payload_in_a_colour_is_refused(client, auth_headers):
    resp = await client.put(
        "/api/branding",
        headers=auth_headers,
        json={"colors": {"accent": "#fff; background-image: url(//evil)"}},
    )
    assert resp.status_code == 400


# -------------------------------------------------------------------------- images


def test_a_png_data_uri_is_accepted():
    assert validate_image(PNG, field="Logo").startswith("data:image/png;base64,")


def test_an_svg_is_accepted():
    assert validate_image(SVG, field="Logo").startswith("data:image/svg+xml;base64,")


@pytest.mark.parametrize(
    "payload",
    [
        "https://evil.example.com/logo.png",       # a remote URL, not an upload
        "data:text/html;base64," + base64.b64encode(b"<script>").decode(),
        "data:image/png,notbase64",                # missing the base64 marker
        "data:image/png;base64,!!!not base64!!!",
        "data:image/png;base64,",                  # empty
        "javascript:alert(1)",
    ],
)
def test_a_payload_that_is_not_an_image_upload_is_refused(payload):
    with pytest.raises(BrandingError):
        validate_image(payload, field="Logo")


def test_an_oversized_image_is_refused():
    big = "data:image/png;base64," + base64.b64encode(b"x" * (2 * 1024 * 1024)).decode()
    with pytest.raises(BrandingError) as exc:
        validate_image(big, field="Logo")
    assert "limit" in str(exc.value)


def test_the_stored_image_is_re_encoded_not_passed_through():
    """Whatever reaches an <img src> is bytes we decoded ourselves."""
    sneaky = "data:image/png;base64," + base64.b64encode(b"hello").decode() + "\n\n"
    assert "\n" not in validate_image(sneaky, field="Logo")


# --------------------------------------------------------------------------- rules


@pytest.mark.asyncio
async def test_branding_is_readable_without_logging_in(client):
    """The sign-in screen is branded before anyone has authenticated."""
    resp = await client.get("/api/branding")
    assert resp.status_code == 200
    assert resp.json()["customised"] is False


@pytest.mark.asyncio
async def test_only_an_admin_can_change_it(client, auth_headers):
    headers = await _plain_user(client, auth_headers)
    assert (await client.put("/api/branding", headers=headers, json={})).status_code == 403
    assert (await client.delete("/api/branding", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_saving_colours_does_not_drop_the_logo(client, auth_headers):
    """The form does not resend images, so omitting one must not delete it."""
    await client.put("/api/branding", headers=auth_headers, json={"logo": PNG})
    resp = await client.put(
        "/api/branding", headers=auth_headers, json={"colors": {"accent": "#1a73e8"}}
    )
    assert resp.json()["logo"].startswith("data:image/png")
    assert resp.json()["colors"] == {"accent": "#1a73e8"}


@pytest.mark.asyncio
async def test_an_explicit_empty_string_removes_an_image(client, auth_headers):
    await client.put("/api/branding", headers=auth_headers, json={"logo": PNG})
    resp = await client.put("/api/branding", headers=auth_headers, json={"logo": ""})
    assert resp.json()["logo"] == ""


@pytest.mark.asyncio
async def test_reset_restores_the_shipped_look(client, auth_headers):
    await client.put(
        "/api/branding",
        headers=auth_headers,
        json={"app_name": "Acme Gateway", "logo": PNG, "colors": {"accent": "#1a73e8"}},
    )
    assert (await client.get("/api/branding")).json()["customised"] is True

    resp = await client.delete("/api/branding", headers=auth_headers)
    assert resp.json()["customised"] is False
    assert (await client.get("/api/branding")).json()["app_name"] == ""


@pytest.mark.asyncio
async def test_light_and_dark_palettes_are_kept_apart(client, auth_headers):
    resp = await client.put(
        "/api/branding",
        headers=auth_headers,
        json={"colors": {"accent": "#0f7a4d"}, "colors_dark": {"accent": "#3dcf8e"}},
    )
    assert resp.json()["colors"]["accent"] == "#0f7a4d"
    assert resp.json()["colors_dark"]["accent"] == "#3dcf8e"


@pytest.mark.asyncio
async def test_a_partial_palette_is_allowed(client, auth_headers):
    """A company sets its accent and leaves the rest of the design alone."""
    resp = await client.put(
        "/api/branding", headers=auth_headers, json={"colors": {"accent": "#1a73e8"}}
    )
    assert resp.json()["colors"] == {"accent": "#1a73e8"}


@pytest.mark.asyncio
async def test_branding_travels_in_a_backup(client, auth_headers):
    """A company that migrates keeps its look without redoing it."""
    await client.put(
        "/api/branding",
        headers=auth_headers,
        json={"app_name": "Acme Gateway", "colors": {"accent": "#1a73e8"}},
    )
    backup = (
        await client.post("/api/backup/export", headers=auth_headers, json={})
    ).json()
    assert backup["payload"]["branding"]["app_name"] == "Acme Gateway"

    await client.delete("/api/branding", headers=auth_headers)
    await client.post(
        "/api/backup/restore",
        headers=auth_headers,
        json={"data": backup, "mode": "replace"},
    )
    assert (await client.get("/api/branding")).json()["app_name"] == "Acme Gateway"
