"""Cles VAPID (Web Push) : generation et lecture, quel que soit leur format.

pywebpush n'accepte PAS une cle privee au format PEM passee en texte : il la
lit comme du base64 et echoue avec "Could not deserialize key data". Ce
module ramene toute cle (PEM multiligne, PEM colle sur une ligne avec des \\n
litteraux, ou forme brute) a la forme brute base64url qu'il comprend.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    value = value.strip()
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def generate_vapid_keys() -> tuple[str, str]:
    """Rend (cle publique, cle privee), toutes deux en base64url.

    La publique (65 octets, point non compresse) va au navigateur, dans
    applicationServerKey. La privee (32 octets) reste sur le serveur.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(private)


def private_key_for_pywebpush(raw: str) -> str:
    """Cle privee VAPID sous la forme brute base64url, quelle que soit l'entree."""
    value = (raw or "").strip().replace("\\n", "\n")
    if "BEGIN" in value:
        key = serialization.load_pem_private_key(value.encode("utf-8"), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("La cle VAPID doit etre une cle EC P-256")
        return _b64url(key.private_numbers().private_value.to_bytes(32, "big"))
    return value


def public_key_is_valid(public: str) -> bool:
    """Une cle publique VAPID valide : 65 octets commencant par 0x04."""
    try:
        data = _b64url_decode(public)
    except (ValueError, TypeError):
        return False
    return len(data) == 65 and data[0] == 4
