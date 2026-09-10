import base64
import json
import os
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.models import AuditEntry
from webgate.auth.models import ApiKey, User
from webgate.backup.models import BACKUP_FORMAT
from webgate.branding.store import Branding
from webgate.servers.crypto import decrypt_value, encrypt_value
from webgate.servers.models import Server
from webgate.webhooks.models import Webhook

KDF_ITERATIONS = 480_000
AUDIT_LIMIT = 5000


# --------------------------------------------------------------------------- crypto


def _derive(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def seal(payload: dict[str, Any], passphrase: str) -> dict[str, str]:
    """Encrypt a payload under a passphrase, carrying the salt alongside it."""
    salt = os.urandom(16)
    token = Fernet(_derive(passphrase, salt)).encrypt(json.dumps(payload).encode())
    return {
        "kdf": "pbkdf2-sha256",
        "iterations": str(KDF_ITERATIONS),
        "salt": base64.b64encode(salt).decode(),
        "ciphertext": token.decode(),
    }


def unseal(blob: dict[str, Any], passphrase: str) -> dict[str, Any]:
    salt = base64.b64decode(blob["salt"])
    iterations = int(blob.get("iterations", KDF_ITERATIONS))
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return json.loads(Fernet(key).decrypt(blob["ciphertext"].encode()).decode())


# --------------------------------------------------------------------------- backup


async def build_backup(
    session: AsyncSession, *, passphrase: str, include_audit: bool, version: str
) -> dict[str, Any]:
    with_credentials = bool(passphrase)

    servers = (await session.execute(select(Server))).scalars().all()
    by_id = {s.id: s for s in servers}

    server_rows: list[dict[str, Any]] = []
    for s in servers:
        row: dict[str, Any] = {
            "name": s.name,
            "hostname": s.hostname,
            "port": s.port,
            "username": s.username,
            "auth_method": s.auth_method,
            "group": s.group,
            "tags": json.loads(s.tags or "[]"),
            "description": s.description,
            "ssh_enabled": s.ssh_enabled,
            "sftp_enabled": s.sftp_enabled,
            "sftp_allowed_paths": json.loads(s.sftp_allowed_paths or "[]"),
            "sftp_read_only": s.sftp_read_only,
            # Referencing the jump host by NAME is what makes a backup portable.
            # Ids are reassigned by the target database, so an id would silently
            # point at whatever server happens to land on it.
            "jump_via_name": by_id[s.jump_via_id].name if s.jump_via_id in by_id else None,
        }
        if with_credentials:
            # Decrypted here, re-encrypted with the target's key on restore.
            row["password"] = decrypt_value(s.encrypted_password)
            row["private_key"] = decrypt_value(s.encrypted_private_key)
        server_rows.append(row)

    users = (await session.execute(select(User))).scalars().all()
    user_rows = [
        {
            "username": u.username,
            "hashed_password": u.hashed_password,
            "is_admin": u.is_admin,
            "must_change_password": u.must_change_password,
            "allowed_groups": json.loads(u.allowed_groups or "[]"),
            "totp_secret": u.totp_secret if with_credentials else "",
            "totp_enabled": u.totp_enabled if with_credentials else False,
        }
        for u in users
    ]
    user_by_id = {u.id: u.username for u in users}

    hooks = (await session.execute(select(Webhook))).scalars().all()
    hook_rows = [
        {
            "name": w.name,
            "url": w.url,
            "events": json.loads(w.events or '["*"]'),
            "enabled": w.enabled,
            "secret": w.secret if with_credentials else "",
            "owner": user_by_id.get(w.user_id),
        }
        for w in hooks
    ]

    keys = (await session.execute(select(ApiKey))).scalars().all()
    key_rows = [
        {
            "name": k.name,
            "key_hash": k.key_hash,
            "key_prefix": k.key_prefix,
            "owner": user_by_id.get(k.user_id),
        }
        for k in keys
    ]

    audit_rows: list[dict[str, Any]] = []
    if include_audit:
        entries = (
            (
                await session.execute(
                    select(AuditEntry).order_by(AuditEntry.id.desc()).limit(AUDIT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        audit_rows = [
            {
                "username": e.username,
                "action": e.action,
                "detail": e.detail,
                "ip_address": e.ip_address,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in reversed(entries)
        ]

    brand = (await session.execute(select(Branding).limit(1))).scalar_one_or_none()
    branding_row = (
        {
            "app_name": brand.app_name,
            "tagline": brand.tagline,
            "favicon_emoji": brand.favicon_emoji,
            "colors": brand.colors,
            "colors_dark": brand.colors_dark,
            "logo": brand.logo,
            "login_image": brand.login_image,
            "favicon": brand.favicon,
        }
        if brand is not None
        else None
    )

    payload = {
        "branding": branding_row,
        "servers": server_rows,
        "users": user_rows,
        "webhooks": hook_rows,
        "api_keys": key_rows,
        "audit": audit_rows,
    }

    envelope: dict[str, Any] = {
        "webgate_backup": BACKUP_FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "source_version": version,
        "encrypted": with_credentials,
        "includes_credentials": with_credentials,
        "counts": {k: len(v) for k, v in payload.items() if isinstance(v, list)},
        # Session recordings are files on disk, not database rows; they are not
        # carried here and must be copied separately.
        "excludes": ["session_recordings"],
    }
    if with_credentials:
        envelope["sealed"] = seal(payload, passphrase)
    else:
        envelope["payload"] = payload
    return envelope


# -------------------------------------------------------------------------- restore


def read_payload(data: dict[str, Any], passphrase: str) -> dict[str, Any]:
    if data.get("webgate_backup") != BACKUP_FORMAT:
        raise ValueError(
            f"Unsupported backup format {data.get('webgate_backup')!r}; expected {BACKUP_FORMAT}"
        )
    if data.get("encrypted"):
        if not passphrase:
            raise ValueError("This backup is encrypted. Enter the passphrase used to create it.")
        try:
            return unseal(data["sealed"], passphrase)
        except (InvalidToken, KeyError, ValueError) as exc:
            raise ValueError("Wrong passphrase, or the backup file is damaged.") from exc
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Backup file has no readable payload.")
    return payload


async def restore_backup(
    session: AsyncSession, payload: dict[str, Any], *, mode: str, actor_id: int
) -> dict[str, Any]:
    created = {"servers": 0, "users": 0, "webhooks": 0, "api_keys": 0}
    skipped = {"servers": 0, "users": 0, "webhooks": 0, "api_keys": 0}
    warnings: list[str] = []

    if mode == "replace":
        # Servers first: they carry a self-referencing FK.
        await session.execute(delete(Server))
        await session.execute(delete(Webhook))
        await session.execute(delete(ApiKey))
        await session.flush()

    # ---- users (never deleted; a restore must not lock the operator out) ----
    existing_users = {u.username: u for u in (await session.execute(select(User))).scalars().all()}
    for row in payload.get("users", []):
        name = row.get("username")
        if not name or name in existing_users:
            skipped["users"] += 1
            continue
        user = User(
            username=name,
            hashed_password=row.get("hashed_password", ""),
            is_admin=bool(row.get("is_admin")),
            must_change_password=bool(row.get("must_change_password")),
            allowed_groups=json.dumps(row.get("allowed_groups", [])),
            totp_secret=row.get("totp_secret", ""),
            totp_enabled=bool(row.get("totp_enabled")),
        )
        session.add(user)
        existing_users[name] = user
        created["users"] += 1
    await session.flush()

    # ---- servers, in two passes so jump hosts resolve by name ----
    existing_servers = {s.name: s for s in (await session.execute(select(Server))).scalars().all()}
    pending: list[tuple[Server, str]] = []
    for row in payload.get("servers", []):
        name = row.get("name")
        if not name or name in existing_servers:
            skipped["servers"] += 1
            continue
        server = Server(
            name=name,
            hostname=row.get("hostname", ""),
            port=int(row.get("port", 22) or 22),
            username=row.get("username", ""),
            auth_method=row.get("auth_method", "password"),
            encrypted_password=encrypt_value(row.get("password", "")),
            encrypted_private_key=encrypt_value(row.get("private_key", "")),
            group=row.get("group", ""),
            tags=json.dumps(row.get("tags", [])),
            description=row.get("description", ""),
            ssh_enabled=bool(row.get("ssh_enabled", True)),
            sftp_enabled=bool(row.get("sftp_enabled", True)),
            sftp_allowed_paths=json.dumps(row.get("sftp_allowed_paths", [])),
            sftp_read_only=bool(row.get("sftp_read_only", False)),
            user_id=actor_id,
        )
        session.add(server)
        existing_servers[name] = server
        created["servers"] += 1
        if row.get("jump_via_name"):
            pending.append((server, row["jump_via_name"]))
    await session.flush()

    for server, jump_name in pending:
        target = existing_servers.get(jump_name)
        if target is None:
            warnings.append(
                f"{server.name}: jump host {jump_name!r} is not in this backup or on this "
                f"instance — the hop was left unset rather than pointed at the wrong host."
            )
            continue
        server.jump_via_id = target.id

    # ---- webhooks ----
    existing_hooks = {w.name for w in (await session.execute(select(Webhook))).scalars().all()}
    for row in payload.get("webhooks", []):
        name = row.get("name")
        if not name or name in existing_hooks:
            skipped["webhooks"] += 1
            continue
        owner = existing_users.get(row.get("owner") or "")
        session.add(
            Webhook(
                name=name,
                url=row.get("url", ""),
                events=json.dumps(row.get("events", ["*"])),
                enabled=bool(row.get("enabled", True)),
                secret=row.get("secret", ""),
                user_id=owner.id if owner else actor_id,
            )
        )
        existing_hooks.add(name)
        created["webhooks"] += 1

    # ---- api keys (hashes only; the plaintext key was never stored) ----
    existing_keys = {
        (k.name, k.key_prefix) for k in (await session.execute(select(ApiKey))).scalars().all()
    }
    for row in payload.get("api_keys", []):
        ident = (row.get("name"), row.get("key_prefix"))
        if not ident[0] or ident in existing_keys:
            skipped["api_keys"] += 1
            continue
        owner = existing_users.get(row.get("owner") or "")
        session.add(
            ApiKey(
                name=row["name"],
                key_hash=row.get("key_hash", ""),
                key_prefix=row.get("key_prefix", ""),
                user_id=owner.id if owner else actor_id,
            )
        )
        existing_keys.add(ident)
        created["api_keys"] += 1

    # Branding is company configuration, so it moves with the rest of the state.
    brand_row = payload.get("branding")
    if isinstance(brand_row, dict):
        existing = (await session.execute(select(Branding).limit(1))).scalar_one_or_none()
        if existing is None:
            existing = Branding(id=1)
            session.add(existing)
        elif mode != "replace":
            warnings.append("Branding already set here; the backup's look was not applied.")
            brand_row = None
        if brand_row is not None:
            for field in (
                "app_name", "tagline", "favicon_emoji", "colors",
                "colors_dark", "logo", "login_image", "favicon",
            ):
                setattr(existing, field, brand_row.get(field) or "")

    await session.commit()

    if payload.get("audit"):
        warnings.append(
            f"{len(payload['audit'])} audit entries were in the backup but are not "
            f"replayed — the audit log records what happened on this instance."
        )
    return {"mode": mode, "created": created, "skipped": skipped, "warnings": warnings}
