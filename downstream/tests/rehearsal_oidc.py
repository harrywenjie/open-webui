"""Loopback OpenID Connect fixture serving one synthetic member to one client."""

import base64
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


def make_handler(issuer, callback, client_secret):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_key.update(kid="fixture", alg="RS256", use="sig")
    client_id = "fixture-client"
    basic = "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    claims = {"sub": "fixture-subject", "name": "Fixture member", "email": "member@example.org", "email_verified": True}
    codes = {}
    metadata = {
        "issuer": issuer,
        "authorization_endpoint": issuer + "/authorize",
        "token_endpoint": issuer + "/token",
        "jwks_uri": issuer + "/keys",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        "scopes_supported": ["openid", "profile", "email"],
    }

    class FixtureIssuer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def json_response(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/.well-known/openid-configuration":
                return self.json_response(metadata)
            if url.path == "/keys":
                return self.json_response({"keys": [public_key]})
            q = parse_qs(url.query)
            if (
                url.path != "/authorize"
                or q.get("client_id") != [client_id]
                or q.get("redirect_uri") != [callback]
                or q.get("response_type") != ["code"]
                or not q.get("state")
                or not q.get("nonce")
            ):
                return self.send_error(400)
            code = secrets.token_urlsafe(24)
            codes[code] = q["nonce"][0]
            location = callback + "?" + urlencode({"code": code, "state": q["state"][0]})
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def do_POST(self):
            if self.path != "/token" or not secrets.compare_digest(self.headers.get("Authorization", ""), basic):
                return self.send_error(401)
            form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode())
            if form.get("redirect_uri") != [callback] or form.get("grant_type") != ["authorization_code"]:
                return self.send_error(400)
            nonce = codes.pop(form.get("code", [""])[0], None)
            if nonce is None:
                return self.send_error(400)
            now = int(time.time())
            token = jwt.encode(
                {**claims, "iss": issuer, "aud": client_id, "iat": now, "exp": now + 120, "nonce": nonce},
                private_key,
                algorithm="RS256",
                headers={"kid": "fixture"},
            )
            self.json_response(
                {
                    "access_token": secrets.token_urlsafe(24),
                    "token_type": "Bearer",
                    "expires_in": 120,
                    "id_token": token,
                }
            )

    return FixtureIssuer
