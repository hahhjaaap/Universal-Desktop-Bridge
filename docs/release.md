# Verify a Windows release

The v0.14.0 publication workflow is **manual-only** and requires owner review of
paired Windows upgrade/rollback and end-to-end acceptance evidence. It first
checks the exact `main` revision's required push CI, builds and tests the
Windows package, and stages three validated assets:

- `udb-windows-x64.zip`
- `SHA256SUMS`
- `install.ps1`

A separate, narrowly privileged publication job checks the ZIP checksum and
installer source bytes, **attests all three assets, and verifies all three
attestations against the expected repository, workflow, `main` ref and source
commit before creating the public GitHub release**. This is not Authenticode
code signing. It does not imply that every machine or Cloudflare deployment has
been upgraded.

**After** publication, GitHub Actions verifies the published tag, the HTTPS
asset digests and a disposable Windows installation. If that last step fails,
the release may already be visible: investigate the failed workflow and do
not install or redistribute its assets until the issue is resolved.

## Verify downloaded assets

Use a current GitHub CLI with `gh attestation` support. For example, after
the owner has actually published `v0.14.0`, use PowerShell:

```powershell
$repo = "hahhjaaap/Universal-Desktop-Bridge"
$tag = "v0.14.0"
$sourceSha = gh api "repos/$repo/git/ref/tags/$tag" --jq '.object.sha'
if ($LASTEXITCODE -ne 0 -or $sourceSha -notmatch '^[a-f0-9]{40}$') {
    throw "Cannot verify the release tag source revision."
}
gh release download $tag --repo $repo --pattern "udb-windows-x64.zip" --pattern "SHA256SUMS" --pattern "install.ps1" --dir .
if ($LASTEXITCODE -ne 0) { throw "Cannot download the exact release assets." }

foreach ($asset in @("udb-windows-x64.zip", "SHA256SUMS", "install.ps1")) {
    gh attestation verify ".\$asset" --repo $repo `
        --signer-workflow "$repo/.github/workflows/one-command-release.yml" `
        --source-ref refs/heads/main --source-digest $sourceSha
    if ($LASTEXITCODE -ne 0) {
        throw "Invalid or missing build provenance for $asset."
    }
}
$shaLine = (Get-Content .\SHA256SUMS -Raw).Trim()
$actual = (Get-FileHash .\udb-windows-x64.zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($shaLine -cne "$actual  udb-windows-x64.zip") {
    throw "Published ZIP and SHA256SUMS disagree."
}
```

Run these checks on the exact tag you intend to install; do not replace the
tag with `latest` while comparing against a previously recorded SHA. A
successful attestation establishes which GitHub Actions workflow built those
specific bytes from that repository and source commit. An ordinary SHA-256
file, on its own, only checks integrity relative to the downloaded checksum.

**The current UDB Windows EXE remains unsigned by Authenticode.** An
attestation is not a Windows executable publisher signature, and an unsigned
EXE may trigger Windows trust warnings. Obtain and verify a trusted
Authenticode signer separately for a signed distribution. See
[Windows release security](release-security.md) and the
[GitHub CLI verification reference](https://cli.github.com/manual/gh_attestation_verify).

The remaining real-device release requirements and manual review are documented
in [the version/acceptance matrix](current-version.md) and
[FastPath end-to-end acceptance](fastpath-e2e-acceptance.md).
