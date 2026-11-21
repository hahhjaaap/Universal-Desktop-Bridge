"""Release builds must not leave a write-scoped token in checkout config."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_checkout_disables_persisted_write_token():
    workflow = (ROOT / ".github" / "workflows" / "one-command-release.yml").read_text(
        encoding="utf-8"
    )
    assert "contents: write" in workflow
    checkouts = re.findall(
        r"uses: actions/checkout@[a-f0-9]{40} # v7\n(.*?)(?=\n      - )",
        workflow,
        re.DOTALL,
    )
    assert len(checkouts) == 2
    assert all("persist-credentials: false" in checkout for checkout in checkouts)
    assert "persist-credentials: true" not in workflow
    # Export the token only to steps that need GitHub API access.
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert not any(line.startswith("      GH_TOKEN:") for line in workflow.splitlines())
