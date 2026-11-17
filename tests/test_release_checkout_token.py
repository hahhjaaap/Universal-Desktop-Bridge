"""Release builds must not leave a write-scoped token in checkout config."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_checkout_disables_persisted_write_token():
    workflow = (
        ROOT / ".github" / "workflows" / "one-command-release.yml"
    ).read_text(encoding="utf-8")
    assert "contents: write" in workflow
    assert workflow.count("uses: actions/checkout@v7") == 1
    checkout = workflow.split("- uses: actions/checkout@v7", 1)[1].split(
        "- uses: actions/setup-python@v7", 1
    )[0]
    assert "persist-credentials: false" in checkout
    assert "persist-credentials: true" not in workflow
    # The explicit token should be used only in the two release gate/publish
    # steps, not exported job-wide to dependency installation.
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "      GH_TOKEN: ${{ github.token }}" not in workflow
