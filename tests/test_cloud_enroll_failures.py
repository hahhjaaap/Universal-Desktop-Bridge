"""Developer Cloudflare enrollment must not leak the administrator secret."""

from __future__ import annotations

import sys
from urllib.error import HTTPError

import pytest

from tools import cloud_enroll
from udb.cloud_pair import NoRedirect


def setup_bootstrap(monkeypatch, tmp_path, relay="https://example.workers.dev"):
    monkeypatch.setattr(
        sys,
        "argv",
        ["cloud_enroll.py", "--relay", relay, "--home", str(tmp_path)],
    )
    monkeypatch.setenv("UDB_ADMIN_KEY", "s" * 48)


def test_bootstrap_refuses_non_cloudflare_origin_before_opening_network(
    monkeypatch, tmp_path
):
    setup_bootstrap(monkeypatch, tmp_path, "https://evil.example")
    monkeypatch.setattr(
        cloud_enroll,
        "build_opener",
        lambda *_args: pytest.fail("must never call attacker origin"),
    )
    with pytest.raises(SystemExit):
        cloud_enroll.main()
    assert not (tmp_path / "cloud-pairing.json").exists()


def test_bootstrap_refuses_redirect_without_forwarding_admin_key(monkeypatch, tmp_path):
    setup_bootstrap(monkeypatch, tmp_path)
    seen = []

    class Redirect:
        def open(self, request, timeout):
            seen.append((request, timeout))
            raise HTTPError(
                request.full_url,
                302,
                "redirect",
                {"Location": "https://evil.example"},
                None,
            )

    def opener(handler):
        assert isinstance(handler, NoRedirect)
        return Redirect()

    monkeypatch.setattr(cloud_enroll, "build_opener", opener)
    with pytest.raises(RuntimeError, match="HTTP 302"):
        cloud_enroll.main()
    assert len(seen) == 1
    assert seen[0][1] == 20
    assert seen[0][0].full_url.startswith("https://example.workers.dev/")
    assert not (tmp_path / "cloud-pairing.json").exists()


def test_bootstrap_timeout_is_unknown_without_local_token(monkeypatch, tmp_path):
    setup_bootstrap(monkeypatch, tmp_path)

    class TimedOut:
        def open(self, _request, timeout):
            assert timeout == 20
            raise TimeoutError("upstream may already have committed")

    monkeypatch.setattr(cloud_enroll, "build_opener", lambda _handler: TimedOut())
    with pytest.raises(RuntimeError, match="outcome unknown"):
        cloud_enroll.main()
    assert not (tmp_path / "cloud-pairing.json").exists()
    assert not (tmp_path / "cloud-device-token").exists()
