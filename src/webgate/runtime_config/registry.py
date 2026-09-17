"""What an admin is allowed to change while webgate is running.

This registry is the single source of truth: the admin panel is generated from it,
values are validated against it, and adding a setting means one entry here and
nothing else -- no migration, no HTML, no endpoint.

Not everything belongs here. Three kinds of setting stay in the environment:

* **Bootstrap.** `db_url` and `secret_key` cannot live in the database -- one is how
  you reach it, the other decrypts what is inside it.
* **Process.** `host`, `port`, `root_path`, `log_level` and `instance_id` are read
  once, before the app can serve a request that would change them.
* **Footguns.** `demo_mode` is a deployment posture, and turning it on from the UI
  would be a one-way door: it blocks the writes needed to turn it back off.
  `jwt_algorithm` is one typo away from disabling signature verification.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["bool", "int", "text", "secret", "choice"]


class InvalidSetting(ValueError):
    """A submitted value the registry refuses."""


@dataclass(frozen=True)
class Spec:
    key: str
    section: str
    label: str
    help: str
    kind: Kind
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    placeholder: str = ""
    # Shown in red in the panel: the admin is loosening something.
    warning: str = ""
    check: Callable[[Any], None] | None = field(default=None, compare=False)

    def coerce(self, raw: Any) -> Any:
        """Validate and normalise a submitted value, or raise InvalidSetting."""
        if self.kind == "bool":
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str) and raw.lower() in {"true", "false"}:
                return raw.lower() == "true"
            raise InvalidSetting(f"{self.label} must be true or false")

        if self.kind == "int":
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise InvalidSetting(f"{self.label} must be a whole number") from None
            if self.minimum is not None and value < self.minimum:
                raise InvalidSetting(f"{self.label} must be at least {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise InvalidSetting(f"{self.label} must be at most {self.maximum}")
            return value

        if not isinstance(raw, str):
            raise InvalidSetting(f"{self.label} must be text")
        value = raw.strip()

        if self.kind == "choice" and value not in self.choices:
            raise InvalidSetting(f"{self.label} must be one of: {', '.join(self.choices)}")

        if self.check is not None:
            self.check(value)
        return value


# ------------------------------------------------------------------- validators


def _https_url(value: str) -> None:
    if value and not value.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise InvalidSetting(
            "Must be an https:// URL. Tokens and codes travel over this, so plain http "
            "is only acceptable against localhost."
        )


def _must_contain(token: str):
    def check(value: str) -> None:
        if value and token not in value.split():
            raise InvalidSetting(f"Must include {token}")

    return check


def _ldap_url(value: str) -> None:
    if value and not value.startswith(("ldap://", "ldaps://")):
        raise InvalidSetting("LDAP URL must start with ldap:// or ldaps://")


def _json_object(value: str) -> None:
    if not value:
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InvalidSetting(f"Not valid JSON: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise InvalidSetting('Must be a JSON object, e.g. {"ldap-admins": "infra"}')


def _json_array(value: str) -> None:
    if not value:
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InvalidSetting(f"Not valid JSON: {exc.msg}") from None
    if not isinstance(parsed, list):
        raise InvalidSetting('Must be a JSON list, e.g. ["ldap-admins"]')


def _has_placeholder(token: str) -> Callable[[str], None]:
    def check(value: str) -> None:
        if value and token not in value:
            raise InvalidSetting(f"Must contain {token}, which is replaced at lookup time")

    return check


SPECS: tuple[Spec, ...] = (
    # ------------------------------------------------------------------ security
    Spec(
        key="verify_host_keys",
        section="Security",
        label="Verify SSH host keys",
        help=(
            "Record each server's host key on first connection and refuse to connect if "
            "it changes later. Accepting a new key stays an admin decision."
        ),
        kind="bool",
        warning=(
            "With this off, webgate sends stored credentials to whatever answers on a "
            "server's address. Only reasonable in a throwaway lab."
        ),
    ),
    Spec(
        key="jwt_expire_minutes",
        section="Security",
        label="Session token lifetime",
        help=(
            "Minutes a sign-in stays valid. Tokens already issued keep the lifetime "
            "they were given."
        ),
        kind="int",
        minimum=5,
        maximum=43200,  # 30 days
    ),
    Spec(
        key="session_timeout",
        section="Security",
        label="Idle SSH timeout",
        help=(
            "Seconds an SSH session may sit with no input or output before it is closed. "
            "0 disables it."
        ),
        kind="int",
        minimum=0,
        maximum=86400,
    ),
    Spec(
        key="max_sessions_per_user",
        section="Security",
        label="Concurrent SSH sessions per user",
        help=(
            "How many terminals one account may hold open on a single worker. 0 means "
            "no limit. Counted per worker, so a gateway behind a load balancer allows "
            "this many on each."
        ),
        kind="int",
        minimum=0,
        maximum=200,
        warning=(
            "0 means nothing stops a looping browser tab from opening SSH sessions "
            "until the worker runs out."
        ),
    ),
    Spec(
        key="max_upload_size",
        section="Security",
        label="Maximum transfer size",
        help=(
            "Bytes. Applies to uploads and to downloads, which are read into the gateway "
            "before being sent on. 0 removes the limit."
        ),
        kind="int",
        minimum=0,
        maximum=100 * 1024 * 1024 * 1024,
        warning=(
            "0 means a single large file can exhaust the gateway's memory and take down "
            "every session on this worker."
        ),
    ),
    # ---------------------------------------------------------------- monitoring
    Spec(
        key="disable_monitor",
        section="Monitoring",
        label="Disable status checks",
        help="Stop probing servers for their online/offline dot.",
        kind="bool",
    ),
    Spec(
        key="monitor_interval",
        section="Monitoring",
        label="Check interval",
        help="Seconds between full sweeps of the registry.",
        kind="int",
        minimum=10,
        maximum=3600,
    ),
    Spec(
        key="monitor_timeout",
        section="Monitoring",
        label="Check timeout",
        help="Seconds to wait for a server to answer before calling it offline.",
        kind="int",
        minimum=1,
        maximum=120,
    ),
    Spec(
        key="monitor_concurrency",
        section="Monitoring",
        label="Parallel checks",
        help="How many servers are probed at once. Raise it for a large fleet.",
        kind="int",
        minimum=1,
        maximum=200,
    ),
    Spec(
        key="monitor_alert_after",
        section="Monitoring",
        label="Failures before alerting",
        help=(
            "Consecutive failed checks before a server is reported down over a "
            "webhook. 1 alerts on the first blip; the default waits for a second."
        ),
        kind="int",
        minimum=1,
        maximum=10,
    ),
    # ----------------------------------------------------------------- recording
    Spec(
        key="record_sessions",
        section="Recording",
        label="Allow session recording",
        help=(
            "Lets servers record their SSH sessions to asciinema cast files, replayable "
            "in the browser. Each server must also opt in separately, so a sandbox and a "
            "production bastion are not held to the same policy by accident."
        ),
        kind="bool",
        warning="Recordings capture everything typed and printed, including anything secret.",
    ),
    Spec(
        key="recording_max_bytes",
        section="Recording",
        label="Maximum recording size",
        help=(
            "Bytes per session. A recording that reaches it stops and says so inside the "
            "replay, rather than ending as though the session crashed. 0 removes the cap."
        ),
        kind="int",
        minimum=0,
        maximum=1024 * 1024 * 1024,
    ),
    # ----------------------------------------------------------- single sign-on
    Spec(
        key="oidc_enabled",
        section="Single sign-on",
        label="Enable single sign-on",
        help=(
            "Adds a sign-in button that sends people to your identity provider. Local "
            "accounts and LDAP keep working alongside it."
        ),
        kind="bool",
    ),
    Spec(
        key="oidc_display_name",
        section="Single sign-on",
        label="Button label",
        help='What the sign-in button says. Blank shows "single sign-on".',
        kind="text",
        placeholder="Acme SSO",
    ),
    Spec(
        key="oidc_issuer",
        section="Single sign-on",
        label="Issuer URL",
        help=(
            "The provider's base URL. Everything else is read from "
            "{issuer}/.well-known/openid-configuration, so there is nothing else to copy."
        ),
        kind="text",
        placeholder="https://login.microsoftonline.com/<tenant>/v2.0",
        check=_https_url,
    ),
    Spec(
        key="oidc_client_id",
        section="Single sign-on",
        label="Client ID",
        help="From the application you registered with the provider.",
        kind="text",
    ),
    Spec(
        key="oidc_client_secret",
        section="Single sign-on",
        label="Client secret",
        help=(
            "Stored encrypted, and never returned by the API. Leave blank for a public "
            "client; the flow uses PKCE either way."
        ),
        kind="secret",
    ),
    Spec(
        key="oidc_scopes",
        section="Single sign-on",
        label="Scopes",
        help="Must include openid. Add the scope your provider needs for group claims.",
        kind="text",
        placeholder="openid profile email groups",
        check=_must_contain("openid"),
    ),
    Spec(
        key="oidc_username_claim",
        section="Single sign-on",
        label="Username claim",
        help=(
            "Which claim becomes the webgate username. Entra ID and Okta send "
            "preferred_username; some providers only send email."
        ),
        kind="text",
        placeholder="preferred_username",
    ),
    Spec(
        key="oidc_groups_claim",
        section="Single sign-on",
        label="Groups claim",
        help="Which claim carries group membership. Blank means nobody gets any group.",
        kind="text",
        placeholder="groups",
    ),
    Spec(
        key="oidc_group_map",
        section="Single sign-on",
        label="Group mapping",
        help=(
            'JSON, provider group to webgate group: {"infra-oncall": "prod"}. A group '
            "that is not mapped grants nothing, so a new directory group cannot quietly "
            "open a server group of the same name."
        ),
        kind="text",
        placeholder='{"infra-oncall": "prod"}',
        check=_json_object,
    ),
    Spec(
        key="oidc_admin_groups",
        section="Single sign-on",
        label="Admin groups",
        help="JSON list of provider groups whose members become webgate admins.",
        kind="text",
        placeholder='["infra-admins"]',
        check=_json_array,
    ),
    Spec(
        key="oidc_redirect_base",
        section="Single sign-on",
        label="Public URL",
        help=(
            "Only needed when the gateway cannot work out its own public address -- "
            "behind a proxy that rewrites the host, say. The redirect URI registered "
            "with your provider is this plus /api/auth/sso/callback."
        ),
        kind="text",
        placeholder="https://webgate.example.com",
        check=_https_url,
    ),
    # ---------------------------------------------------------------------- LDAP
    Spec(
        key="ldap_enabled",
        section="LDAP",
        label="Enable LDAP sign-in",
        help="Try LDAP when local authentication fails. Local accounts keep working.",
        kind="bool",
    ),
    Spec(
        key="ldap_url",
        section="LDAP",
        label="Server URL",
        help="ldaps:// is strongly preferred; ldap:// sends the bind password in the clear.",
        kind="text",
        placeholder="ldaps://ldap.example.com:636",
        check=_ldap_url,
    ),
    Spec(
        key="ldap_bind_dn",
        section="LDAP",
        label="Bind DN",
        help="Service account used to search the directory. Leave blank for an anonymous bind.",
        kind="text",
        placeholder="cn=svc-webgate,ou=services,dc=example,dc=com",
    ),
    Spec(
        key="ldap_bind_password",
        section="LDAP",
        label="Bind password",
        help="Stored encrypted, and never returned by the API once saved.",
        kind="secret",
    ),
    Spec(
        key="ldap_user_base",
        section="LDAP",
        label="User search base",
        help="Where to look for accounts.",
        kind="text",
        placeholder="ou=people,dc=example,dc=com",
    ),
    Spec(
        key="ldap_user_filter",
        section="LDAP",
        label="User filter",
        help="{username} is replaced with the escaped name being signed in.",
        kind="text",
        placeholder="(uid={username})",
        check=_has_placeholder("{username}"),
    ),
    Spec(
        key="ldap_group_base",
        section="LDAP",
        label="Group search base",
        help="Leave blank to skip group lookup entirely.",
        kind="text",
        placeholder="ou=groups,dc=example,dc=com",
    ),
    Spec(
        key="ldap_group_filter",
        section="LDAP",
        label="Group filter",
        help="{dn} is replaced with the escaped DN of the user who just signed in.",
        kind="text",
        placeholder="(member={dn})",
        check=_has_placeholder("{dn}"),
    ),
    Spec(
        key="ldap_group_map",
        section="LDAP",
        label="Group mapping",
        help='JSON, directory group to webgate group: {"infra-oncall": "prod"}',
        kind="text",
        placeholder='{"infra-oncall": "prod"}',
        check=_json_object,
    ),
    Spec(
        key="ldap_admin_groups",
        section="LDAP",
        label="Admin groups",
        help="JSON list of directory groups whose members become webgate admins.",
        kind="text",
        placeholder='["infra-admins"]',
        check=_json_array,
    ),
)

BY_KEY: dict[str, Spec] = {s.key: s for s in SPECS}

SECTIONS: tuple[str, ...] = tuple(dict.fromkeys(s.section for s in SPECS))
