"""Key material and the trust policy for A2A Agent Card signatures (ADR-0013).

The whole point of a signed Agent Card is that a caller can tell *this* agent
from something that merely claims to be it. That only holds if the verifier's
key comes from somewhere the card cannot influence. So:

  * the public key ships in the repo (``keys/<kid>.pub.pem``) and is pinned by
    key id — ``interchange-2026-09``;
  * the private key never touches git. It lives in an environment variable
    (``A2A_SIGNING_KEY_PEM``) on the deployed server, or in a throwaway pair the
    offline demo generates for itself;
  * ``key_provider`` refuses **any** ``jku`` (the JWS "fetch my key from this
    URL" header). Following one would let whoever handed us the card also hand
    us the key that validates it — the signature would prove nothing;
  * verification pins ``algorithms=["ES256"]`` so a card cannot talk the
    verifier into a weaker algorithm (the classic ``alg`` confusion attack).

Overrides exist for the offline demo, which has no deployed key: set
``A2A_PINNED_PUBLIC_KEY_PEM`` (full PEM text) and optionally ``A2A_PINNED_KID``
and the pin moves to that key for that process only.
"""
from __future__ import annotations

import os
import pathlib

from a2a.utils.signing import (  # re-exported: callers assert on these
    InvalidSignaturesError,
    NoSignatureError,
    SignatureVerificationError,
    create_signature_verifier,
)

__all__ = [
    "KID",
    "PINNED_PUBLIC_KEYS",
    "PinnedKeyError",
    "active_kid",
    "generate_keypair",
    "key_provider",
    "load_private_key_pem",
    "make_verifier",
    "pinned_public_keys",
    "InvalidSignaturesError",
    "NoSignatureError",
    "SignatureVerificationError",
]

#: The key id this agent signs with, and the only one a client trusts by default.
KID = "interchange-2026-09"

KEY_DIR = pathlib.Path(__file__).parent / "keys"

#: Env var holding the full private-key PEM on the deployed server. Never a path
#: into the repo, and never committed.
PRIVATE_KEY_ENV = "A2A_SIGNING_KEY_PEM"
#: Env overrides used by the offline demo (ephemeral pair, no deployed key).
PUBLIC_KEY_ENV = "A2A_PINNED_PUBLIC_KEY_PEM"
KID_ENV = "A2A_PINNED_KID"


class PinnedKeyError(SignatureVerificationError, ValueError):
    """The card asked for key material we refuse to supply.

    Both a ``SignatureVerificationError`` (it is a verification failure) and a
    ``ValueError`` (the request itself was invalid), so either assertion holds.
    """


def _load_pinned_from_disk() -> dict[str, str]:
    """The committed public key(s), keyed by kid. Missing file -> empty pin set."""
    pem = KEY_DIR / f"{KID}.pub.pem"
    return {KID: pem.read_text(encoding="utf-8")} if pem.exists() else {}


#: kid -> public-key PEM. Loaded once from the committed ``keys/`` directory;
#: tests monkeypatch it, and the env override below layers on top of it.
PINNED_PUBLIC_KEYS: dict[str, str] = _load_pinned_from_disk()


def active_kid() -> str:
    """The kid this process signs with (and pins, unless told otherwise)."""
    return os.environ.get(KID_ENV) or KID


def pinned_public_keys() -> dict[str, str]:
    """The trusted kid -> PEM map for *this* call.

    Read at call time rather than import time so the demo (and tests) can point
    the pin at an ephemeral key without reimporting the module.
    """
    trusted = dict(PINNED_PUBLIC_KEYS)
    env_pem = os.environ.get(PUBLIC_KEY_ENV)
    if env_pem:
        trusted[active_kid()] = env_pem
    return trusted


def load_private_key_pem() -> str | None:
    """The signing key from the environment, or None when this process has none.

    A server with no private key serves an *unsigned* card rather than failing to
    start — a pinned client will then refuse it (``NoSignatureError``), which is
    the correct outcome and a loud one.
    """
    pem = os.environ.get(PRIVATE_KEY_ENV)
    return pem if pem and pem.strip() else None


def key_provider(kid: str | None, jku: str | None) -> str:
    """Return the pinned PEM for ``kid`` — or refuse.

    Called by the SDK verifier once per signature, with the `kid` and `jku` read
    out of that signature's protected header. Both refusals are the trust policy,
    not an error path: a non-empty ``jku`` is an attempt to choose the key that
    checks the signature, and an unknown ``kid`` is a key we never agreed to trust.
    """
    if jku:
        raise PinnedKeyError(
            f"refusing to fetch verification key from jku={jku!r}: key material "
            "comes only from the pinned set, never from a URL the card supplies"
        )
    trusted = pinned_public_keys()
    if not kid or kid not in trusted:
        raise PinnedKeyError(
            f"unknown kid {kid!r}: not in the pinned key set {sorted(trusted)}"
        )
    return trusted[kid]


def make_verifier():
    """An Agent Card signature verifier bound to our pinned keys and ES256 only.

    Raises ``NoSignatureError`` for an unsigned card, ``InvalidSignaturesError``
    when no signature validates (a tampered card), and ``PinnedKeyError`` when
    the card names a key we do not trust.
    """
    return create_signature_verifier(key_provider, algorithms=["ES256"])


def generate_keypair() -> tuple[str, str]:
    """Generate a fresh ES256 (P-256) pair; return ``(private_pem, public_pem)``.

    Used by ``make a2a-keygen`` (to mint the deployed key) and by the offline
    demo and tests (to mint a throwaway one). Nothing here writes to disk — the
    caller decides where a private key may live, and the repo is never it.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


if __name__ == "__main__":  # `python -m a2a_agent.keys` == make a2a-keygen
    priv, pub = generate_keypair()
    print(priv, end="")
    print(pub, end="")
