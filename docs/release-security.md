# Windows release trust and signing

**Status (2026-11-01):** UDB's published v0.10.0 standalone installer is
SHA-256 checked, but **not Authenticode-signed**. A SHA256SUMS file generated
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

After a future publisher signing certificate is provisioned, on Windows:

```powershell
python tools/verify_signed_release.py dist/udb-windows-x64.zip --signer-thumbprint YOUR_40_HEX_CHARACTER_CERTIFICATE_THUMBPRINT
```

A nonzero exit means there is no trusted matching signature; never treat this
as success. The fingerprint is an identifier for the pinned certificate; it
is **not** the cryptographic digest of a file.

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
