"""Tests unitaires — app/core/security.py.

Pas de DB, pas de FastAPI ici : uniquement les fonctions pures de hashing,
signature de jeton, et TOTP.
"""

import time

import pyotp

from app.core.security import (
    create_pending_2fa_token,
    create_session_token,
    generate_csrf_token,
    generate_totp_secret,
    hash_password,
    read_pending_2fa_token,
    read_session_token,
    totp_provisioning_uri,
    verify_password,
    verify_totp_code,
)


def test_hash_password_roundtrip():
    hashed = hash_password("un-mot-de-passe-solide")
    assert hashed != "un-mot-de-passe-solide"
    assert verify_password("un-mot-de-passe-solide", hashed) is True
    assert verify_password("mauvais-mot-de-passe", hashed) is False


def test_hash_password_produces_different_hashes_each_time():
    # bcrypt inclut un sel aléatoire : deux hash du même mot de passe diffèrent.
    h1 = hash_password("secret123")
    h2 = hash_password("secret123")
    assert h1 != h2
    assert verify_password("secret123", h1)
    assert verify_password("secret123", h2)


def test_session_token_roundtrip():
    token = create_session_token(user_id=42)
    assert read_session_token(token) == 42


def test_session_token_rejects_tampering():
    token = create_session_token(user_id=42)
    # Modifie un caractère au milieu du token plutôt que le dernier : le
    # dernier caractère base64 d'une signature HMAC n'encode que 2 bits
    # significatifs (padding), donc environ 6% des tampering sur CE
    # caractère précis ne changent pas la valeur décodée et la signature
    # reste valide par coïncidence — un vrai artefact de l'encodage, pas
    # une faille de sécurité (vérifié empiriquement : ~310/5000 collisions
    # en ne testant que le dernier caractère). Le milieu du token n'a pas
    # ce problème : n'importe quel caractère y est pleinement significatif.
    middle = len(token) // 2
    tampered_char = "a" if token[middle] != "a" else "b"
    tampered = token[:middle] + tampered_char + token[middle + 1:]
    assert read_session_token(tampered) is None


def test_session_token_rejects_garbage():
    assert read_session_token("ceci-nest-pas-un-jeton-valide") is None


def test_pending_2fa_token_roundtrip():
    token = create_pending_2fa_token(user_id=7)
    assert read_pending_2fa_token(token) == 7


def test_pending_2fa_token_distinct_namespace_from_session_token():
    # Un jeton de session ne doit pas être valide comme jeton "pending 2FA"
    # (salts de signature différents) — évite un contournement du 2FA.
    session_token = create_session_token(user_id=1)
    assert read_pending_2fa_token(session_token) is None


def test_generate_totp_secret_is_valid_base32_and_usable():
    secret = generate_totp_secret()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert verify_totp_code(secret, code) is True


def test_verify_totp_code_rejects_wrong_code():
    secret = generate_totp_secret()
    assert verify_totp_code(secret, "000000") in (True, False)  # ne doit pas planter
    wrong_totp_secret = generate_totp_secret()
    wrong_code = pyotp.TOTP(wrong_totp_secret).now()
    # Très improbable que les deux secrets produisent le même code au même instant.
    if wrong_code == pyotp.TOTP(secret).now():
        time.sleep(1)
    assert verify_totp_code(secret, wrong_code) is False


def test_verify_totp_code_rejects_non_numeric():
    secret = generate_totp_secret()
    assert verify_totp_code(secret, "abcdef") is False
    assert verify_totp_code(secret, "") is False


def test_totp_provisioning_uri_contains_issuer_and_email():
    secret = generate_totp_secret()
    uri = totp_provisioning_uri(secret, "test@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "test%40example.com" in uri or "test@example.com" in uri
    assert "WFM" in uri


def test_generate_csrf_token_is_random_and_url_safe():
    t1 = generate_csrf_token()
    t2 = generate_csrf_token()
    assert t1 != t2
    assert len(t1) > 20
