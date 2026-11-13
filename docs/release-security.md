# Windows release trust and signing

> **UDB 0.12.0 docs review (2026-11-13):** **Current UDB 0.12.0 source guidance.** Verify the installed executable, Cloudflare Worker, OAuth and owner grants separately; source changes do not update them. See [version/status](current-version.md).

**Published v0.12.0 release status (2026-11-13):** UDB's latest published v0.12.0 standalone installer is
SHA-256 checked, but **not Authenticode-signed**, as confirmed by its release notes. A SHA256SUMS file generated
by the same release workflow detects accidental corruption but does not, on
its own, authenticate the publisher against a compromised release workflow.

This document describes what is implemented, what is required for a
signature-enforced release, and what remains unverified. It does **not**
claim a completed security audit or signed Windows release.

## Implemented verification capability

`tools/verify_signed_release.py` extracts only `UDB/udb.exe` from a
standalone release ZIP into a disposable local directory and asks Windows
`Get-AuthenticodeSignature` to verify a **Valid** signature. It additionally
pins the expected certificate thumbprint, rather than accepting an arbitrary
signed publisher. It has a bounded payload size and does not execute the EXE,
install software, access owner state or query the network.

## Archive manifest consistency is not publisher authentication

The signed-release candidate verifier also checks **all** members of the
standalone ZIP against its `STANDALONE-SHA256SUMS` manifest. It rejects
missing/extra/duplicate members, Windows case-colliding names, traversal,
symlink entries, oversized members, malformed checksums and mismatched file
hashes. This catches ordinary repackaging errors such as signing
`dist/udb.exe` *after* creating a ZIP without updating the embedded EXE and
checksums.

**Important limitation:** `STANDALONE-SHA256SUMS` is stored in the same
ZIP and is not itself signed. An attacker able to replace both a file and
the manifest can recompute matching hashes. Authenticode verification on
`udb.exe` authenticates that executable, **not** the companion installer
script, runtime DLLs, manifests or extra helper scripts. Public beta still
requires an independently authenticated artifact provenance / release
attestation and verified signing of executable code, plus an operator-approved
release workflow. A green manifest check alone is **not** a public-release
security pass.

After a future publisher signing certificate is provisioned, on Windows:

```powershell
python tools/verify_signed_release.py dist/udb-windows-x64.zip --signer-thumbprint YOUR_40_HEX_CHARACTER_CERTIFICATE_THUMBPRINT
```

A nonzero exit means there is no trusted matching signature; never treat this
as success. The fingerprint is an identifier for the pinned certificate; it
is **not** the cryptographic digest of a file.

## Opt-in pinned-signer installer mode

The Windows installer now accepts an **optional** `-RequireSignerThumbprint`
switch containing one owner-approved 40-character Authenticode signer
certificate thumbprint. When supplied, the installer checks Windows
`Get-AuthenticodeSignature` for **Valid** status and the exact pinned
certificate on the extracted `udb.exe`, **before** it is moved into the
managed releases folder or executed. It also checks any retained executable
chosen for rollback before switching. Missing, invalid or explicitly empty
pins are rejected when the parameter is provided.

Example for a **future, independently approved signed channel**:

```powershell
.\install.ps1 -FeedUrl https://example.org/approved-signed-udb-feed -RequireSignerThumbprint YOUR_APPROVED_40_HEX_CERTIFICATE_PIN
```

The certificate pin must be communicated through a separate authenticated
operator channel, **not** fetched from the same unsigned ZIP or webpage being
verified. The example is illustrative and does not designate an approved feed
or a real signer. Any failed signature check aborts activation without
switching the active release. A successful signature still does **not**
authenticate `install.ps1` itself or all companion files.

**Compatibility:** The option is disabled unless explicitly supplied. Existing
unsigned developer installs still run as before, and must not be advertised
as signed or public-beta-ready. Do not enable this for a real deployment until
signing infrastructure and a signed artifact are provisioned. An operator
using the pinned mode to roll back to an earlier **unsigned** release will
receive an intentional denial. Do not silently disable the pin to bypass it.

## Required work before shipping a signed edition

1. Obtain an organization-appropriate code signing identity, secure its
   private key in an HSM or approved hosted signing service, and configure
   narrowly scoped release credentials. Do not commit a PFX, recovery
   secret or access token into GitHub or a user's computer.
2. Sign the **exact executable included in the release archive** before
   creating ZIP checksums. Signing a separate `dist/udb.exe` after the ZIP
   is built is insufficient. Repack the verified signed executable,
   regenerate the archive's internal manifest and public checksum, and
   verify the final archive.
3. Verify the trusted signer certificate and chain, including how certificate
   renewal and key compromise are handled. Test on clean Windows 10/11.
4. Add a dedicated **fail-closed release gate** calling the verifier on the
   exact archive *before publication*, with an independently reviewed signer
   pin. Never label an unsigned build `verified signed`.
5. Protect GitHub Actions release workflow with environment approvals,
   least-privilege tokens, pinned actions where practical, trusted build
   provenance and recorded hashes. Test installer update and rollback on
   actual Windows machines.
6. Run independent manual security assessment of the native permissions,
   browser/CDP isolation, path races, approval spoofing, tunneling and MCP
   prompt injection; document residual risks.

**The current publishing workflow does not yet do step 1–4.** Do not add an
unconditional signing pass to an unsigned release workflow without first
providing signing infrastructure and reworking packaging order; otherwise
the next version bump would only fail instead of producing a secure build.

## Release channels and compatibility

UDB source changes merged to `main` do not update an installed Windows
`udb.exe`. The published stable release and real-device acceptance are
separate steps. Before updating, check the released tag, verify signatures
and hashes using a trusted publisher identity, read the security advisories,
and keep a safe rollback path. A successful CI matrix alone does not
establish a signed or independently audited product.

## Source mitigation: fail-closed publication without protected main (2026-11-13)

The `one-command-windows-release` workflow evaluates `tools/release_gate.py`
for the exact main SHA and successful CI. The source now also checks GitHub's
`branches/main.protected` flag **for that same main SHA**. When the flag is
false, unreadable or stale, a new Windows release is **not** published; no
branch-protection setting or credential is changed by this check.

This is a defense-in-depth publication gate, **not branch protection itself**.
A repository administrator must still configure effective required PR reviews,
Linux/Windows/Cloudflare/installer checks, stale-review dismissal, force-push
restrictions, protected tags and staging environment approval in GitHub Settings
(see [issue #147](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/147)).
Verify enforcement as a non-bypass actor before closing the issue. Public
GitHub metadata and a passing source test do not prove the repository is
protected or that a particular Windows binary is a signed public release.
