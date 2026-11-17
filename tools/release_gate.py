"""Publish only the current main revision after its complete CI matrix passes."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


def qualifying_run(run, repository, sha):
    return (
        run.get("head_sha") == sha
        and run.get("head_branch") == "main"
        and run.get("event") == "push"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("path", "").split("@")[0] == ".github/workflows/ci.yml"
        and run.get("head_repository", {}).get("full_name") == repository
    )


def authorized_manual_dispatch(
    repository, event_name, ref, actor, triggering_actor, repository_owner
):
    """Only the repository owner can explicitly authorize unprotected releases.

    A second user re-running an owner's workflow must not inherit the
    original dispatch's release privilege. Missing runner identity fails closed.
    """
    owner, separator, _ = repository.partition("/")
    return bool(
        separator
        and owner
        and repository_owner == owner
        and event_name == "workflow_dispatch"
        and ref == "refs/heads/main"
        and actor == owner
        and triggering_actor == owner
    )


def decide(
    repository,
    sha,
    main_sha,
    runs,
    release_exists,
    *,
    main_protected=False,
    allow_unprotected_manual=False,
):
    if sha != main_sha:
        return {"publish": False, "reason": "A newer main revision exists"}
    if not main_protected and not allow_unprotected_manual:
        return {
            "publish": False,
            "reason": "Main branch is not protected; release publication blocked",
        }
    if not any(qualifying_run(run, repository, sha) for run in runs):
        raise ValueError(
            "The exact main revision has no successful complete push CI run"
        )
    if release_exists:
        return {"publish": False, "reason": "This version is already published"}
    return {"publish": True, "reason": "Current main revision passed complete CI"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", type=int)
    parser.add_argument(
        "--manual-unprotected",
        action="store_true",
        help="Explicit manual release approval on main only; full push CI remains required.",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise ValueError("Invalid repository")
    if not re.fullmatch(r"[a-f0-9]{40}", args.sha):
        raise ValueError("Invalid source revision")
    if args.manual_unprotected and not authorized_manual_dispatch(
        args.repository,
        os.environ.get("GITHUB_EVENT_NAME"),
        os.environ.get("GITHUB_REF"),
        os.environ.get("GITHUB_ACTOR"),
        os.environ.get("GITHUB_TRIGGERING_ACTOR"),
        os.environ.get("GITHUB_REPOSITORY_OWNER"),
    ):
        raise ValueError(
            "Unprotected release requires an owner-triggered manual dispatch on main"
        )
    root = Path(__file__).resolve().parents[1]
    version_file = (root / "src/udb/_version.py").read_text(encoding="utf-8")
    match = re.fullmatch(r'VERSION = "(\d+\.\d+\.\d+)"\s*', version_file)
    if not match:
        raise ValueError("Invalid canonical release version")
    version = match[1]

    def api(path, *, missing_ok=False):
        request = urllib.request.Request(
            "https://api.github.com/repos/" + args.repository + "/" + path,
            headers={
                "Authorization": "Bearer " + os.environ["GH_TOKEN"],
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "UDB-release-gate",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise RuntimeError(
                f"GitHub release gate request failed (HTTP {exc.code})"
            ) from None

    main_sha = api("git/ref/heads/main")["object"]["sha"]
    # Fail closed if the public branch metadata does not prove that the same
    # main revision is protected. Required reviews/checks still need separate
    # administrator verification; this is only the publication safety gate.
    branch = api("branches/main")
    main_protected = (
        branch.get("protected") is True
        and branch.get("commit", {}).get("sha") == main_sha
    )
    if args.run_id:
        runs = [api(f"actions/runs/{args.run_id}")]
    else:
        runs = api(
            f"actions/workflows/ci.yml/runs?head_sha={args.sha}&branch=main&event=push&per_page=100"
        )["workflow_runs"]
    release = api("releases/tags/v" + version, missing_ok=True)
    result = decide(
        args.repository,
        args.sha,
        main_sha,
        runs,
        release is not None,
        main_protected=main_protected,
        allow_unprotected_manual=args.manual_unprotected,
    )
    result.update(version=version, sha=args.sha)
    print(json.dumps(result))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(
                f"publish={str(result['publish']).lower()}\nversion={version}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
