"""
ASP.NET Identity 2 password hashing and password policy (U01 P1, 01d A6/A9/A10).

Hash format [Code: Microsoft.AspNet.Identity.Core 2.1 `Crypto.HashPassword`, used by
cp-web and cp-api]: base64( 0x00 | salt[16] | PBKDF2-HMAC-SHA1(password, salt, 1000)[32] ).
Phase 1 must write exactly this format so UAT/prod cp-web and cp-api keep accepting
passwords set by the new API (PT2).

Password policy [Code `CrystalPower.Infrastructure/Configuration/ApplicationUserManager.cs`]:
RequiredLength 6, RequireNonLetterOrDigit, RequireDigit, RequireLowercase, RequireUppercase.
The messages are the Identity 2 English resources; Identity joins them with one space
into a single error.

Never log passwords or hashes.
"""

import base64
import hashlib
import hmac
import secrets
import unicodedata
import uuid

from pydantic import BaseModel


_FORMAT_MARKER = 0x00
_SALT_SIZE = 16
_SUBKEY_SIZE = 32
_ITERATIONS = 1000
_HASH_SIZE = 1 + _SALT_SIZE + _SUBKEY_SIZE


def _subkey(password: str, salt: bytes) -> bytes:
    # .NET Rfc2898DeriveBytes(string, ...) encodes the password as UTF-8.
    return hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), salt, _ITERATIONS, _SUBKEY_SIZE)


def hash_password(password: str) -> str:
    """Identity v2 hash of `password` (new random salt every call)."""
    salt = secrets.token_bytes(_SALT_SIZE)
    return base64.b64encode(bytes([_FORMAT_MARKER]) + salt + _subkey(password, salt)).decode(
        "ascii"
    )


def verify_password(hashed: str | None, password: str | None) -> bool:
    """`Crypto.VerifyHashedPassword`: False for a missing/malformed hash; constant-time compare."""
    if not hashed or password is None:
        return False
    try:
        raw = base64.b64decode(hashed, validate=True)
    except (ValueError, TypeError):
        return False
    if len(raw) != _HASH_SIZE or raw[0] != _FORMAT_MARKER:
        return False
    salt = raw[1 : 1 + _SALT_SIZE]
    expected = raw[1 + _SALT_SIZE :]
    return hmac.compare_digest(expected, _subkey(password, salt))


def new_security_stamp() -> str:
    """Identity 2 `UpdateSecurityStamp`: `Guid.NewGuid().ToString()` (lower-case, hyphens)."""
    return str(uuid.uuid4())


# ── Password policy ─────────────────────────────────────────────────────────


class PasswordPolicy(BaseModel):
    required_length: int = 6
    require_non_letter_or_digit: bool = True
    require_digit: bool = True
    require_lowercase: bool = True
    require_uppercase: bool = True


LEGACY_POLICY = PasswordPolicy()


def _is_letter_or_digit(ch: str) -> bool:
    # .NET Char.IsLetterOrDigit: Unicode letter (L*) or decimal digit (Nd).
    cat = unicodedata.category(ch)
    return cat.startswith("L") or cat == "Nd"


def password_policy_errors(
    password: str | None, policy: PasswordPolicy = LEGACY_POLICY
) -> str | None:
    """Identity 2 `PasswordValidator.ValidateAsync`; None when valid, else the joined message."""
    value = password or ""
    errors: list[str] = []
    if len(value) < policy.required_length:
        errors.append(f"Passwords must be at least {policy.required_length} characters.")
    if policy.require_non_letter_or_digit and all(_is_letter_or_digit(c) for c in value):
        errors.append("Passwords must have at least one non letter or digit character.")
    if policy.require_digit and not any("0" <= c <= "9" for c in value):
        errors.append("Passwords must have at least one digit ('0'-'9').")
    if policy.require_lowercase and not any("a" <= c <= "z" for c in value):
        errors.append("Passwords must have at least one lowercase ('a'-'z').")
    if policy.require_uppercase and not any("A" <= c <= "Z" for c in value):
        errors.append("Passwords must have at least one uppercase ('A'-'Z').")
    return " ".join(errors) if errors else None
