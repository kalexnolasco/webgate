import base64
import hashlib

from cryptography.fernet import Fernet

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


def decrypt_value(token: str) -> str:
    if not token:
        return ""
    return get_fernet().decrypt(token.encode()).decode()
