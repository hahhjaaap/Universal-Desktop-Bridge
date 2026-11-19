"""Release builds must not leave a write-scoped token in checkout config."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_checkout_disables_persisted_write_token():
    workflow = (ROOT / ".github" / "workflows" / "one-command-release.yml").read_text(
        encoding="utf-8"
    )
    assert "contents: write" in workflow
    assert len(re.findall(r"uses: actions/checkout@[a-f0-9]{40} # v7", workflow)) == 1
    checkout = workflow.split("- uses: actions/checkout@", 1)[1].split(
        "- uses: actions/setup-python@", 1
    )[0]
    assert "persist-credentials: false" in checkout
    assert "persist-credentials: true" not in workflow
    # The explicit token should be used only in the two release gate/publish
    # steps, not exported job-wide to dependency installation.
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert not any(line.startswith("      GH_TOKEN:") for line in workflow.splitlines())
