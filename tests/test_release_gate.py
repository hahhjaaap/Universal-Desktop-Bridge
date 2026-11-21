"""A release must use the exact trusted, tested main revision."""

import pytest

from tools.release_gate import (
    REQUIRED_PUSH_WORKFLOWS,
    authorized_manual_dispatch,
    decide,
)

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


def green_runs(**changes):
    return [
        run(**{"path": workflow, **changes}) for workflow in REQUIRED_PUSH_WORKFLOWS
    ]


def test_release_gate_requires_green_codeql_and_runtime_audit():
    for workflow in REQUIRED_PUSH_WORKFLOWS:
        runs = [r for r in green_runs() if r["path"] != workflow]
        runs.append(run(path=workflow, conclusion="failure"))
        with pytest.raises(ValueError, match=workflow):
            decide(REPOSITORY, SHA, SHA, runs, False, main_protected=True)


def test_release_gate_skips_existing_version_and_superseded_commit():
    assert decide(REPOSITORY, SHA, SHA, green_runs(), False, main_protected=True)[
        "publish"
    ]
    assert not decide(REPOSITORY, SHA, SHA, green_runs(), True, main_protected=True)[
        "publish"
    ]
    assert not decide(
        REPOSITORY, SHA, "b" * 40, green_runs(), False, main_protected=True
    )["publish"]


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
        decide(REPOSITORY, SHA, SHA, green_runs(**changes), False, main_protected=True)


def test_release_gate_blocks_automatic_publication_on_unprotected_main():
    result = decide(REPOSITORY, SHA, SHA, green_runs(), False, main_protected=False)
    assert result["publish"] is False
    assert "not protected" in result["reason"]


def test_release_gate_requires_explicit_protection_before_publication():
    assert decide(REPOSITORY, SHA, SHA, green_runs(), False)["publish"] is False
    assert (
        decide(REPOSITORY, SHA, SHA, green_runs(), False, main_protected=True)[
            "publish"
        ]
        is True
    )


def test_manual_unprotected_release_accepts_only_exact_green_main():
    # Explicit owner dispatch may waive branch protection, NEVER CI or SHA matching.
    assert decide(
        REPOSITORY,
        SHA,
        SHA,
        green_runs(),
        False,
        main_protected=False,
        allow_unprotected_manual=True,
    )["publish"]
    assert not decide(
        REPOSITORY,
        SHA,
        "b" * 40,
        green_runs(),
        False,
        main_protected=False,
        allow_unprotected_manual=True,
    )["publish"]
    assert not decide(
        REPOSITORY,
        SHA,
        SHA,
        green_runs(),
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
            green_runs(**changes),
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
    assert "github.actor == github.repository_owner" in workflow
    assert "github.triggering_actor == github.repository_owner" in workflow
    assert workflow.count("--manual-unprotected") == 2
    assert "tools/check_frozen.py" in workflow
    assert "tools/check_installer.py" in workflow
    assert "tools/check_public_installer.py" in workflow
    assert "inputs.confirm_release_acceptance == true" in workflow
    assert "approve_v014_without_live_acceptance:" in workflow
    assert "inputs.approve_v014_without_live_acceptance == true" in workflow
    assert "inputs.confirm_release_acceptance == true ||" in workflow
    assert (
        "The explicit owner live-acceptance waiver is limited to v0.14.0." in workflow
    )
    assert "steps.gate.outputs.version" in workflow
    assert workflow.count("default: false") >= 3
    assert "needs: build" in workflow
    assert (
        workflow.index("actions/attest-build-provenance@")
        < workflow.index("gh attestation verify")
        < workflow.index("gh release create")
        < workflow.index("tools/check_public_installer.py")
    )


def test_owner_initiated_manual_dispatch_on_main_is_allowed():
    assert authorized_manual_dispatch(
        "hahhjaaap/Universal-Desktop-Bridge",
        "workflow_dispatch",
        "refs/heads/main",
        "hahhjaaap",
        "hahhjaaap",
        "hahhjaaap",
    )


@pytest.mark.parametrize(
    ("event", "ref", "actor", "triggering_actor", "repository_owner"),
    [
        ("push", "refs/heads/main", "hahhjaaap", "hahhjaaap", "hahhjaaap"),
        ("workflow_run", "refs/heads/main", "hahhjaaap", "hahhjaaap", "hahhjaaap"),
        ("workflow_dispatch", "refs/heads/dev", "hahhjaaap", "hahhjaaap", "hahhjaaap"),
        (
            "workflow_dispatch",
            "refs/heads/main",
            "collaborator",
            "collaborator",
            "hahhjaaap",
        ),
        (
            "workflow_dispatch",
            "refs/heads/main",
            "hahhjaaap",
            "collaborator",
            "hahhjaaap",
        ),
        (
            "workflow_dispatch",
            "refs/heads/main",
            "collaborator",
            "hahhjaaap",
            "hahhjaaap",
        ),
        ("workflow_dispatch", "refs/heads/main", "hahhjaaap", "hahhjaaap", "other"),
        ("workflow_dispatch", "refs/heads/main", "hahhjaaap", "hahhjaaap", None),
        ("workflow_dispatch", "refs/heads/main", None, "hahhjaaap", "hahhjaaap"),
        ("workflow_dispatch", "refs/heads/main", "hahhjaaap", None, "hahhjaaap"),
    ],
)
def test_manual_release_denies_other_actors_reruns_and_invalid_context(
    event, ref, actor, triggering_actor, repository_owner
):
    assert not authorized_manual_dispatch(
        "hahhjaaap/Universal-Desktop-Bridge",
        event,
        ref,
        actor,
        triggering_actor,
        repository_owner,
    )


def test_manual_release_owner_must_match_repository_identity():
    assert not authorized_manual_dispatch(
        "attacker/other",
        "workflow_dispatch",
        "refs/heads/main",
        "hahhjaaap",
        "hahhjaaap",
        "hahhjaaap",
    )
    assert not authorized_manual_dispatch(
        "hahhjaaap",
        "workflow_dispatch",
        "refs/heads/main",
        "hahhjaaap",
        "hahhjaaap",
        "hahhjaaap",
    )
