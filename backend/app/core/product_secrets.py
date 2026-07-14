from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class ProductSecretEncryptionError(RuntimeError):
    pass


def _get_fernet() -> Fernet:
    key = settings.product_secret_encryption_key
    if not key:
        raise ProductSecretEncryptionError("PRODUCT_SECRET_ENCRYPTION_KEY is required for product secret encryption")
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ProductSecretEncryptionError("PRODUCT_SECRET_ENCRYPTION_KEY is invalid") from exc


def validate_product_secret_encryption_key() -> None:
    _get_fernet()


def encrypt_product_secret(secret: str) -> str:
    if secret == "":
        raise ProductSecretEncryptionError("Product admin secret cannot be empty")
    return _get_fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_product_secret(encrypted_secret: str | None) -> str | None:
    if not encrypted_secret:
        return None
    try:
        return _get_fernet().decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ProductSecretEncryptionError("Product admin secret could not be decrypted") from exc
