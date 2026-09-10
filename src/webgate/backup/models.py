from typing import Any

from pydantic import BaseModel, Field

BACKUP_FORMAT = 1


class BackupRequest(BaseModel):
    # With a passphrase the payload is encrypted and carries server credentials.
    # Without one, credentials are left out and the file is plain JSON.
    passphrase: str = ""
    include_audit: bool = False


class RestoreRequest(BaseModel):
    data: dict[str, Any]
    passphrase: str = ""
    # "merge" keeps what is already there and skips colliding names;
    # "replace" clears servers, webhooks and API keys first. Users are never
    # deleted by a restore — see service.restore_backup.
    mode: str = Field(default="merge", pattern="^(merge|replace)$")


class BackupMeta(BaseModel):
    webgate_backup: int
    created_at: str
    source_version: str
    encrypted: bool
    includes_credentials: bool
    counts: dict[str, int]


class RestoreReport(BaseModel):
    mode: str
    created: dict[str, int]
    skipped: dict[str, int]
    warnings: list[str]
