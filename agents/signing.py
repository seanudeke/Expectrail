"""Per-run verifier-host signing keys (Ed25519).

Private key stays on the verifier host only (``.expectrail-signing-key``).
Public half is published in the morning report / release-candidate.
"""
from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ALGORITHM = "ed25519"
PRIVATE_NAME = ".expectrail-signing-key"
PUBLIC_NAME = ".expectrail-signing-key.pub"


def generate_run_keys(verifier_host: Path) -> dict:
    """Create a fresh Ed25519 keypair under verifier_host. Returns paths + public b64."""
    verifier_host.mkdir(parents=True, exist_ok=True)
    private_path = verifier_host / PRIVATE_NAME
    public_path = verifier_host / PUBLIC_NAME
    for p in (private_path, public_path):
        if p.exists():
            p.unlink()

    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    priv_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_path.write_bytes(priv_raw)
    public_path.write_bytes(pub_raw)
    try:
        private_path.chmod(0o600)
        public_path.chmod(0o644)
    except OSError:
        pass
    public_b64 = base64.b64encode(pub_raw).decode("ascii")
    return {
        "algorithm": ALGORITHM,
        "privatePath": str(private_path),
        "publicPath": str(public_path),
        "publicKey": public_b64,
        "privatePathObj": private_path,
        "publicPathObj": public_path,
    }


def sign_payload(payload: bytes, private_key_raw: bytes) -> str:
    """Return base64 Ed25519 signature over payload."""
    key = Ed25519PrivateKey.from_private_bytes(private_key_raw)
    sig = key.sign(payload)
    return base64.b64encode(sig).decode("ascii")


def verify_payload(payload: bytes, signature_b64: str, public_key_b64: str) -> bool:
    """True if signature verifies with the published public key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pub.verify(base64.b64decode(signature_b64), payload)
        return True
    except Exception:  # noqa: BLE001 — any crypto failure is a failed verify
        return False


def load_public_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")
