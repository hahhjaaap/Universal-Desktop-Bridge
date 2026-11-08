"""Execute the exact D1 device authorization SQL against isolated SQLite data."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "cloudflare" / "migrations" / "0001_tenant_auth.sql"
SOURCE = ROOT / "cloudflare" / "src" / "tenant-store.js"

NOW = 1_800_000_000
A = "a" * 32
B = "b" * 32
ISSUER = "https://p0d-security.cloudflareaccess.com"
ALICE = "7335d417-61da-459d-899c-0a01c76a2f94"
BOB = "7335d417-61da-459d-899c-0a01c76a2f95"


def sql_query() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    section = source.split(
        "export async function authorizedDeviceReadToolsByPrincipal", 1
    )
    assert len(section) == 2
    match = re.search(r"db\.prepare\(`(.*?)`\)\.bind", section[1], re.DOTALL)
    assert match, "D1 query not found: update this acceptance test on schema refactor"
    return match.group(1)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(MIGRATION.read_text(encoding="utf-8"))
    connection.executemany(
        "INSERT INTO tenants(tenant_id, slug, display_name) VALUES (?, ?, ?)",
        [("tenant_a", "tenant-a", "Tenant A"), ("tenant_b", "tenant-b", "Tenant B")],
    )
    connection.executemany(
        "INSERT INTO users(user_id, issuer, subject, email) VALUES (?, ?, ?, ?)",
        [
            ("alice", ISSUER, ALICE, "shared@example.test"),
            ("bob", ISSUER, BOB, "shared@example.test"),
            (
                "owner_b",
                "https://other.cloudflareaccess.com",
                ALICE,
                "third@example.test",
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO tenant_memberships(tenant_id, user_id, role) VALUES (?, ?, ?)",
        [
            ("tenant_a", "alice", "owner"),
            ("tenant_a", "bob", "member"),
            ("tenant_b", "owner_b", "owner"),
        ],
    )
    connection.executemany(
        "INSERT INTO devices(device_id, tenant_id, owner_user_id, label, state) VALUES (?, ?, ?, ?, ?)",
        [
            (A, "tenant_a", "alice", "Windows A", "active"),
            (B, "tenant_b", "owner_b", "Windows B", "active"),
        ],
    )
    connection.executemany(
        "INSERT INTO tool_grants(tenant_id, device_id, user_id, tool_name, granted_by_user_id, granted_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("tenant_a", A, "alice", "bridge_status", "alice", NOW - 100, NOW + 1000),
            ("tenant_a", A, "alice", "read_file", "alice", NOW - 100, NOW + 1000),
            (
                "tenant_b",
                B,
                "owner_b",
                "list_projects",
                "owner_b",
                NOW - 100,
                NOW + 1000,
            ),
        ],
    )
    try:
        yield connection
    finally:
        connection.close()


def allowed(db, device=A, issuer=ISSUER, subject=ALICE, now=NOW):
    return [row[0] for row in db.execute(sql_query(), (device, issuer, subject, now))]


def test_sql_is_valid_and_uses_indexed_device_lookup(db):
    explain = list(
        db.execute("EXPLAIN QUERY PLAN " + sql_query(), (A, ISSUER, ALICE, NOW))
    )
    assert explain
    assert any("devices" in str(row) for row in explain)
    assert allowed(db) == ["bridge_status", "read_file"]


def test_different_subject_with_same_email_does_not_inherit_grant(db):
    assert allowed(db, subject=BOB) == []
    assert allowed(db, issuer="https://other.cloudflareaccess.com") == []
    assert allowed(db, device=B) == []
    assert allowed(db, device=B, issuer="https://other.cloudflareaccess.com") == [
        "list_projects"
    ]


def test_revoked_expired_and_missing_grants_are_denied(db):
    assert allowed(db, now=NOW + 1000) == []
    db.execute(
        "UPDATE tool_grants SET revoked_at = ? WHERE tenant_id = ? AND tool_name = ?",
        (NOW - 5, "tenant_a", "read_file"),
    )
    assert allowed(db) == ["bridge_status"]
    db.execute("DELETE FROM tool_grants WHERE tenant_id = ?", ("tenant_a",))
    assert allowed(db) == []


@pytest.mark.parametrize(
    ("table", "set_clause", "where_clause"),
    [
        ("tenants", "state = 'suspended'", "tenant_id = 'tenant_a'"),
        ("devices", "state = 'revoked'", "device_id = '" + A + "'"),
        ("devices", "revoked_at = 1", "device_id = '" + A + "'"),
        ("users", "state = 'disabled'", "user_id = 'alice'"),
        ("tenant_memberships", "state = 'revoked'", "user_id = 'alice'"),
    ],
)
def test_any_suspended_issuer_owner_or_device_denies_all(
    db, table, set_clause, where_clause
):
    db.execute(f"UPDATE {table} SET {set_clause} WHERE {where_clause}")
    assert allowed(db) == []


def test_sql_parameters_prevent_subject_or_device_injection(db):
    assert allowed(db, subject="' OR 1=1 --") == []
    assert allowed(db, device=A + "' OR 1=1 --") == []


def test_untouched_database_has_no_implicit_permissions():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
        assert allowed(connection) == []
    finally:
        connection.close()
