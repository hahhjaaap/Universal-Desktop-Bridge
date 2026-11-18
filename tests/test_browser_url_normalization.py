"""URL authority parsing must agree with Chromium's special-URL normalization.

Python's urlsplit treats backslash as hostname data; Chromium treats it
like a slash for HTTP(S). A private address with a backslash suffix must
never get through the browser's navigation preflight.
"""

import pytest

from udb.core import PolicyError
from udb.host_browser import validate_url


@pytest.mark.parametrize(
    "url",
    [
        r"http://127.0.0.1\safe.example/",
        r"http://169.254.169.254\latest/meta-data",
        r"http://10.0.0.1\other.example",
        r"http://localhost\settings",
        r"https://metadata.google.internal\latest",
        r"https://public.example\page",
        r"http://127.0.0.1\@public.example",
    ],
)
def test_reject_ambiguous_backslash_navigation(url):
    with pytest.raises(PolicyError, match="URL|host|private"):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "about:blank",
        "https://example.com/path?x=1",
        "http://8.8.8.8/",
        "https://[2606:4700:4700::1111]/",
    ],
)
def test_keep_normal_public_navigation(url):
    assert validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/"],
)
def test_keep_private_url_rejection(url):
    with pytest.raises(PolicyError):
        validate_url(url)
