"""Signer pinning is independent of release archives and owner state."""

import pytest

from tools.verify_signed_release import (
    normalized_thumbprint,
    signature_is_trusted,
)


def test_thumbprint_validation_rejects_truncated_or_injected_values():
    valid = "ab" * 20
    assert normalized_thumbprint("  " + valid + "  ") == valid.upper()
    for invalid in ("", "00" * 19, "abc", "g0" * 20, "00" * 20 + "; echo"):
        with pytest.raises(ValueError):
            normalized_thumbprint(invalid)


def test_valid_signature_must_match_exact_pinned_certificate():
    expected = "11" * 20
    signed = {
        "Status": 0,
        "SignerCertificate": {"Thumbprint": expected.lower(), "Subject": "Example"},
    }
    assert signature_is_trusted(signed, expected)
    assert not signature_is_trusted(
        {"Status": 2, "SignerCertificate": signed["SignerCertificate"]}, expected
    )
    assert not signature_is_trusted(
        {"Status": 0, "SignerCertificate": {"Thumbprint": "22" * 20}}, expected
    )
    assert not signature_is_trusted({"Status": 0, "SignerCertificate": None}, expected)
    assert not signature_is_trusted({}, expected)
