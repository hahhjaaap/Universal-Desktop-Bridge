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


def test_manual_unprotected_release_accepts_only_exact_green_main():
    # Explicit owner dispatch may waive branch protection, NEVER CI or SHA matching.
    assert decide(
        REPOSITORY,
        SHA,
        SHA,
        [run()],
        False,
        main_protected=False,
        allow_unprotected_manual=True,
    )["publish"]
    assert not decide(
        REPOSITORY,
        SHA,
        "b" * 40,
        [run()],
        False,
        main_protected=False,
        allow_unprotected_manual=True,
    )["publish"]
    assert not decide(
        REPOSITORY,
        SHA,
        SHA,
        [run()],
        True,
        main_protected=False,
        allow_unprotected_manual=True,
    )["publish"]


@pytest.mark.parametrize(
    "changes",
    [
        {"head_sha": "b" * 40},
        {"head_branch": "feature"},
        {"event": "pull_request"},
        {"conclusion": "failure"},
        {"status": "in_progress"},
        {"path": ".github/workflows/other.yml"},
        {"head_repository": {"full_name": "fork/bridge"}},
    ],
)
def test_manual_unprotected_cannot_skip_ci(changes):
    with pytest.raises(ValueError, match="no successful"):
        decide(
            REPOSITORY,
            SHA,
            SHA,
            [run(**changes)],
            False,
            allow_unprotected_manual=True,
        )


def test_release_workflow_requires_explicit_manual_confirmation():
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "one-command-release.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "workflow_run:" not in workflow
    assert "confirm_unprotected_release:" in workflow
    assert "default: false" in workflow
    assert "inputs.confirm_unprotected_release == true" in workflow
    assert workflow.count("--manual-unprotected") == 2
    assert "tools/check_frozen.py" in workflow
    assert "tools/check_installer.py" in workflow
    assert "tools/check_public_installer.py" in workflow
