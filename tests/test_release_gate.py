"""A release must use the exact trusted, tested main revision."""

import pytest

from tools.release_gate import decide

REPOSITORY = "owner/bridge"
SHA = "a" * 40


def run(**overrides):
    return dict(
        dict(
            head_sha=SHA,
            head_branch="main",
            event="push",
            status="completed",
            conclusion="success",
            path=".github/workflows/ci.yml",
            head_repository={"full_name": REPOSITORY},
        ),
        **overrides,
    )


def test_release_gate_skips_existing_version_and_superseded_commit():
    assert decide(REPOSITORY, SHA, SHA, [run()], False, main_protected=True)["publish"]
    assert not decide(REPOSITORY, SHA, SHA, [run()], True, main_protected=True)[
        "publish"
    ]
    assert not decide(REPOSITORY, SHA, "b" * 40, [run()], False, main_protected=True)[
        "publish"
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"head_sha": "b" * 40},
        {"head_branch": "feature"},
        {"event": "pull_request"},
        {"status": "in_progress"},
        {"conclusion": "failure"},
        {"path": ".github/workflows/other.yml"},
        {"head_repository": {"full_name": "fork/bridge"}},
    ],
)
def test_release_gate_rejects_incomplete_failed_or_unrelated_ci(changes):
    with pytest.raises(ValueError, match="no successful"):
        decide(REPOSITORY, SHA, SHA, [run(**changes)], False, main_protected=True)


def test_release_gate_blocks_automatic_publication_on_unprotected_main():
    result = decide(REPOSITORY, SHA, SHA, [run()], False, main_protected=False)
    assert result["publish"] is False
    assert "not protected" in result["reason"]


def test_release_gate_requires_explicit_protection_before_publication():
    assert decide(REPOSITORY, SHA, SHA, [run()], False)["publish"] is False
    assert (
        decide(REPOSITORY, SHA, SHA, [run()], False, main_protected=True)["publish"]
        is True
    )
