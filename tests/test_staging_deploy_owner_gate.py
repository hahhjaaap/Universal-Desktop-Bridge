"""Cloudflare staging credentials are available only to the owner's manual job."""

from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "udb-staging-manual-deploy.yml"
)


def test_staging_deploy_requires_owner_dispatch_and_rerun():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "github.event_name == 'workflow_dispatch'" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "github.actor == github.repository_owner" in source
    assert "github.triggering_actor == github.repository_owner" in source
    assert "environment: udb-staging" in source


def test_staging_deploy_does_not_persist_checkout_credentials():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in source
    assert "persist-credentials: false" in source
    assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in source
    assert "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}" in source
    assert "CLOUDFLARE_API_TOKEN:" not in source.split("jobs:", 1)[0]
