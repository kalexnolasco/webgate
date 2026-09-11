"""Refusing to serve the fleet's credentials under a published key.

`WEBGATE_SECRET_KEY` signs every session token and derives the Fernet key that
encrypts every stored SSH password. Its default is in this repository, so a
deployment that never changed it can be handed a valid admin token by anyone.
Nothing checked, and the failure is invisible: everything works.
"""

import pytest

from webgate.__main__ import DEFAULT_SECRET, check_secret_key


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "10.0.0.4", "gateway.internal"])
def test_the_default_key_on_a_reachable_address_stops_startup(host):
    refusal = check_secret_key(DEFAULT_SECRET, host)
    assert refusal is not None
    assert "openssl rand -hex 32" in refusal  # the exact fix
    assert "Backup" in refusal  # and what it costs on an existing install
    assert "WEBGATE_ALLOW_INSECURE_SECRET" in refusal  # and the way past it


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", ""])
def test_the_default_key_on_loopback_only_warns(host, caplog):
    """Trying webgate out on your own machine should not need a ceremony."""
    with caplog.at_level("WARNING"):
        assert check_secret_key(DEFAULT_SECRET, host) is None
    assert "default" in caplog.text


def test_a_real_key_is_never_questioned():
    assert check_secret_key("b1946ac92492d2347c6235b4d2611184", "0.0.0.0") is None


def test_an_operator_can_deliberately_override_it():
    assert check_secret_key(DEFAULT_SECRET, "0.0.0.0", allow_insecure=True) is None


def test_the_refusal_names_what_is_at_risk():
    """An operator who has to decide needs to know what the key protects."""
    refusal = check_secret_key(DEFAULT_SECRET, "0.0.0.0")
    assert "session token" in refusal
    assert "private key" in refusal or "SSH password" in refusal
