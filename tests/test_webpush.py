import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from push import webpush


def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _browser():
    """A fake browser subscription: its private key and the public parts the server gets."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return key, {"p256dh": webpush.b64url(public), "auth": webpush.b64url(auth)}


def _decrypt(body, browser_key, keys):
    """What the phone does (RFC 8291), written independently of webpush.encrypt."""
    salt, record_size, id_len = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_public = body[21 : 21 + id_len]
    assert record_size == 4096 and id_len == 65
    shared = browser_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ua_public = webpush.unb64url(keys["p256dh"])
    ikm = _hkdf(webpush.unb64url(keys["auth"]), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + id_len :], None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypted_payload_decrypts_on_the_phone():
    browser_key, keys = _browser()
    body = webpush.encrypt(b'{"title": "Alert: NVDA"}', keys["p256dh"], keys["auth"])
    assert _decrypt(body, browser_key, keys) == b'{"title": "Alert: NVDA"}'


def test_vapid_header_is_a_valid_es256_jwt():
    key = ec.generate_private_key(ec.SECP256R1())
    private = webpush.b64url(key.private_numbers().private_value.to_bytes(32, "big"))
    header = webpush.vapid_header("https://web.push.apple.com/abc", private, "https://example.cloudfront.net")
    token, k = header.removeprefix("vapid t=").split(", k=")
    head, claims, signature = token.split(".")
    payload = json.loads(webpush.unb64url(claims))
    assert payload["aud"] == "https://web.push.apple.com" and payload["sub"] == "https://example.cloudfront.net"
    raw = webpush.unb64url(signature)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.unb64url(k))
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if wrong


@pytest.mark.parametrize(
    "endpoint, ok",
    [
        ("https://web.push.apple.com/QG", True),
        ("https://fcm.googleapis.com/fcm/send/x", True),
        ("https://wns2-bl2p.notify.windows.com/w/?token=x", True),
        ("http://web.push.apple.com/QG", False),
        ("https://169.254.169.254/latest", False),
        ("https://evil.example/web.push.apple.com", False),
        ("https://web.push.apple.com:8443/QG", False),  # only the standard port
        ("https://user:pw" + "@" + "fcm.googleapis.com/x", False),  # no credentials in the link
        ("https://web.push.apple.com:443/QG", True),
    ],
)
def test_only_known_push_services(endpoint, ok):
    assert webpush.allowed_endpoint(endpoint) is ok


def test_a_redirect_from_a_push_service_is_not_followed() -> None:
    import urllib.request

    from push import webpush

    request = urllib.request.Request("https://web.push.apple.com/x", method="POST")  # noqa: S310
    # No new request is built for the Location header, so the opener raises the 3xx as an HTTPError instead.
    assert webpush._NoRedirects().redirect_request(request, None, 302, "Found", {}, "https://evil.example/") is None
    assert any(isinstance(h, webpush._NoRedirects) for h in webpush._OPENER.handlers)
