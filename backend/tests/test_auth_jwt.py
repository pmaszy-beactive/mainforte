from mainforte.auth.jwt import decode_session, mint_session
from mainforte.auth.passwords import hash_password, verify_password


def test_session_roundtrip():
    tok = mint_session("01USER")
    claims = decode_session(tok)
    assert claims and claims["sub"] == "01USER" and "act_as" not in claims


def test_impersonation_claims():
    tok = mint_session("01SUPER", act_as="01TARGET")
    claims = decode_session(tok)
    assert claims["act_as"] == "01TARGET" and claims["amr"] == ["impersonation"]


def test_password_hash():
    h = hash_password("correct horse")
    assert verify_password("correct horse", h) and not verify_password("wrong", h) and not verify_password("x", None)
