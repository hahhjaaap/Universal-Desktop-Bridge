# Verify a Windows release

The standalone ZIP is published as `udb-windows-x64.zip`. The release workflow
attests the digest of that exact ZIP. A release from before this step was
introduced, or a release whose attestation step fails, can have no matching
attestation. The workflow publishes the archive before the attestation step.

Use a current GitHub CLI with the `attestation` command. From the directory
containing the downloaded ZIP, run the following command before installation.

```powershell
gh attestation verify .\udb-windows-x64.zip --repo hahhjaaap/Universal-Desktop-Bridge --signer-workflow hahhjaaap/Universal-Desktop-Bridge/.github/workflows/one-command-release.yml
```

Only use the artifact if verification succeeds and the reported source revision
matches the release tag you selected. The signed attestation authenticates
the ZIP bytes and the GitHub build provenance. Authenticode serves a separate
purpose by authenticating the publisher of the extracted Windows executable.
An unsigned executable lacks that publisher assurance and can trigger Windows
trust warnings. An unsigned SHA-256 list from the same download location can
detect corruption and provides no independent publisher authentication.

See [Windows signing requirements](release-security.md) and the [GitHub CLI verification reference](https://cli.github.com/manual/gh_attestation_verify).
