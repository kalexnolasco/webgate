import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from webgate.config import settings


def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    return Fernet(_derive_key(settings.secret_key))


def encrypt_value(value: str) -> str:
    if not value:
        return ""
    return get_fernet().encrypt(value.encode()).decode()


class CredentialUnreadable(Exception):
    """Stored credentials will not decrypt with the key this process is using.

    Almost always means WEBGATE_SECRET_KEY changed after the row was written --
    which is exactly what upgrading from the shipped default asks an operator to do.
    Raised as itself rather than as a Fernet error so every caller can say something
    useful instead of returning a 500.
    """

    def __init__(self, what: str = "These credentials") -> None:
        super().__init__(
            f"{what} cannot be decrypted with the current WEBGATE_SECRET_KEY. The key "
            f"changed after they were saved. Restore a backup taken before the change, "
            f"or re-enter the credentials."
        )


def decrypt_value(token: str, what: str = "These credentials") -> str:
    if not token:
        return ""
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CredentialUnreadable(what) from exc
