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


def decide(repository, sha, main_sha, runs, release_exists, *, main_protected=False):
    if sha != main_sha:
        return {"publish": False, "reason": "A newer main revision exists"}
    if not main_protected:
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
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise ValueError("Invalid repository")
    if not re.fullmatch(r"[a-f0-9]{40}", args.sha):
        raise ValueError("Invalid source revision")
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
