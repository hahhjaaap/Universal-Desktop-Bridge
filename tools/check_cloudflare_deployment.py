"""Compatibility entry point for the packaged read-only Cloudflare preflight."""

from udb.cloud_preflight import check
from udb.cloud_preflight import main as _main


def main():
    return _main(checker=check)


if __name__ == "__main__":
    raise SystemExit(main())
