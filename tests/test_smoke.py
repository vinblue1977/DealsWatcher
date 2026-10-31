"""scripts/smoke_test.sh against a small local stand-in for the deployed site and API, so the script itself cannot rot."""

import json
import os
import re
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

BASH = shutil.which("bash") or "/bin/bash"
ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "smoke_test.sh"
SECURITY = {
    "Content-Security-Policy": "default-src 'none'",
    "Strict-Transport-Security": "max-age=31536000",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class Fake:
    """What the stand-in answers; tests change it to break one thing at a time."""

    def __init__(self) -> None:
        self.headers = dict(SECURITY)
        self.open_route: str | None = None  # a route that wrongly answers 200 without a token
        self.config: dict[str, str] | None = None
        self.fallback_ok = True
        self.sw_is_missing = False  # CloudFront answers a missing file with the app's page and status 200
        self.flaky = 0  # answer 503 this many times before working


@pytest.fixture
def fake() -> Iterator[tuple[Fake, str]]:
    state = Fake()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code: int, body: bytes = b"", kind: str = "text/html", headers: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def handle_any(self) -> None:
            if state.flaky:
                state.flaky -= 1
                return self.reply(503, b"busy")
            if self.path.startswith("/me/"):
                open_route = state.open_route == f"{self.command} {self.path}"
                return self.reply(200 if open_route else 401, b"{}", "application/json")
            app = b'<html><body><div id="app"></div></body></html>'
            if self.path == "/":
                return self.reply(200, app, headers=state.headers)
            if self.path == "/no-such-page":
                return self.reply(200 if state.fallback_ok else 403, app if state.fallback_ok else b"denied")
            if self.path == "/config.json":
                host = f"http://127.0.0.1:{self.server.server_port}"
                config = state.config or {"apiUrl": host, "authUrl": "https://auth.example", "clientId": "abc"}
                return self.reply(200, json.dumps(config).encode(), "application/json")
            if self.path == "/sw.js" and state.sw_is_missing:
                return self.reply(200, app)
            kinds = {
                "/manifest.webmanifest": "application/manifest+json",
                "/sw.js": "text/javascript",
                "/icon-192.png": "image/png",
            }
            if self.path in kinds:
                return self.reply(200, b"x", kinds[self.path])
            self.reply(404)

        do_GET = do_POST = do_PUT = do_DELETE = handle_any

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield state, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def smoke(url: str, api: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "TABLE"} | {"SITE": url, "API": api or url, "SMOKE_RETRY_PAUSE": "0"}
    return subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120, check=False)  # noqa: S603 - our own script


def test_passes_when_everything_answers_as_deployed(fake: tuple[Fake, str]) -> None:
    result = smoke(fake[1])
    assert result.returncode == 0, result.stdout
    assert "Smoke test passed" in result.stdout and "FAIL" not in result.stdout
    assert "GET /me/settings -> 401" in result.stdout and "with a bad token -> 401" in result.stdout


def test_fails_when_an_api_route_answers_without_a_token(fake: tuple[Fake, str]) -> None:
    fake[0].open_route = "GET /me/settings"
    result = smoke(fake[1])
    assert result.returncode == 1
    assert "FAIL GET /me/settings -> 200 (want 401)" in result.stdout and "Smoke test FAILED" in result.stdout


def test_fails_when_a_security_header_is_missing(fake: tuple[Fake, str]) -> None:
    del fake[0].headers["Content-Security-Policy"]
    result = smoke(fake[1])
    assert result.returncode == 1 and "FAIL header content-security-policy is missing" in result.stdout


def test_fails_when_the_config_points_at_another_api(fake: tuple[Fake, str]) -> None:
    fake[0].config = {"apiUrl": "https://elsewhere.example", "authUrl": "https://auth.example", "clientId": "abc"}
    result = smoke(fake[1])
    assert result.returncode == 1 and "FAIL config.json" in result.stdout


def test_fails_when_unknown_paths_do_not_fall_back_to_the_app(fake: tuple[Fake, str]) -> None:
    fake[0].fallback_ok = False
    result = smoke(fake[1])
    assert result.returncode == 1 and "FAIL an unknown path does not fall back" in result.stdout


def test_fails_when_a_file_is_answered_with_the_app_page(fake: tuple[Fake, str]) -> None:
    fake[0].sw_is_missing = True
    result = smoke(fake[1])
    assert result.returncode == 1 and "FAIL GET /sw.js" in result.stdout


def test_a_brief_5xx_from_a_fresh_deploy_is_retried(fake: tuple[Fake, str]) -> None:
    fake[0].flaky = 2
    result = smoke(fake[1])
    assert result.returncode == 0, result.stdout


def test_nothing_answering_is_reported_as_000() -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        address = f"http://127.0.0.1:{closed.getsockname()[1]}"  # a port nothing listens on, free again once closed
    result = smoke(address)
    assert result.returncode == 1 and "FAIL GET / -> 000" in result.stdout


def test_a_table_that_is_not_active_fails(fake: tuple[Fake, str], tmp_path: Path) -> None:
    aws = tmp_path / "aws"
    aws.write_text("#!/bin/sh\necho UPDATING\n")
    aws.chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}", "SITE": fake[1], "API": fake[1], "TABLE": "t"}
    result = subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True, check=False)  # noqa: S603 - our own script
    assert result.returncode == 1 and "FAIL table status: UPDATING" in result.stdout
    aws.write_text("#!/bin/sh\necho ACTIVE\n")
    result = subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True, check=False)  # noqa: S603 - our own script
    assert result.returncode == 0 and "ok   table is ACTIVE" in result.stdout


def test_the_probed_routes_are_the_routes_the_stack_defines() -> None:
    stack = set(re.findall(r'\(apigw\.HttpMethod\.(\w+), "(/me/[^"]+)"\)', (ROOT / "infra" / "web.py").read_text()))
    wanted = {(m, p.replace("{id}", "abc")) for m, p in stack}
    script = SCRIPT.read_text()
    listed = set(re.findall(r'"(GET|POST|PUT|DELETE) (/me/[^"\s]+)"', script[script.index("routes=(") : script.index("\n)\n")]))
    assert wanted and listed == wanted


def test_needs_the_site_and_api_addresses() -> None:
    result = subprocess.run(  # noqa: S603 - our own script
        [BASH, str(SCRIPT)], env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0 and "SITE" in result.stderr
