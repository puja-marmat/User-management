"""
Append new random signing keys (JWT_PRIVATE_KEY_PEM, OTP_SIGNING_KEY) to a .env file
without printing them. Needed for any ENVIRONMENT other than local/test (P1-M2).

    uv run python scripts/generate_auth_keys.py            # appends to .env
    uv run python scripts/generate_auth_keys.py path/.env

Refuses when the file already defines either key (only the key names are checked).
"""

from pathlib import Path
import secrets
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


KEYS = ("JWT_PRIVATE_KEY_PEM", "OTP_SIGNING_KEY")


def main(path: Path) -> int:
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            defined = {line.split("=", 1)[0].strip() for line in fh if "=" in line}
        clash = [k for k in KEYS if k in defined]
        if clash:
            print(f"{path} already defines {', '.join(clash)}; nothing written.")
            return 1
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    one_line = pem.strip().replace("\n", "\\n")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f'\nJWT_PRIVATE_KEY_PEM="{one_line}"\nOTP_SIGNING_KEY={secrets.token_hex(32)}\n')
    print(f"Signing keys appended to {path} (values not shown).")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".env")))
