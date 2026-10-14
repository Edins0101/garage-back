"""Hash de contraseñas con scrypt (biblioteca estándar, resistente a fuerza bruta por GPU)."""

import base64
import hashlib
import hmac
import secrets

# Una de las configuraciones de scrypt que recomienda OWASP: N=2^15, r=8, p=3 (~32 MB por hash).
# Se eligió la de menor memoria porque el plan Free de Render tiene 512 MB de RAM.
_N, _R, _P = 2**15, 8, 3
_MAXMEM = 64 * 1024 * 1024


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n), r=int(r), p=int(p),
            maxmem=_MAXMEM,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Hash de relleno para que "usuario inexistente" tarde lo mismo que "contraseña incorrecta".
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
