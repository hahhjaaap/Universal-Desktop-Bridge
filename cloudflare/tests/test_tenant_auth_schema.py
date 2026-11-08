"""Contract test for Cloudflare D1 staging migration using SQLite semantics."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import unittest

SQL = Path(__file__).resolve().parents[1] / "migrations" / "0001_tenant_auth.sql"
NOW = 1_800_000_000


class TenantAuthSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SQL.read_text(encoding="utf-8"))
        self.db.executemany(
            "INSERT INTO tenants(tenant_id,slug,display_name) VALUES (?,?,?)",
            [
                ("t1", "company-one", "Company One"),
                ("t2", "company-two", "Company Two"),
            ],
        )
        self.db.executemany(
            "INSERT INTO users(user_id,issuer,subject) VALUES (?,?,?)",
            [
                ("u1", "https://accounts.example.test", "identity-a"),
                ("u2", "https://accounts.example.test", "identity-b"),
            ],
        )
        self.db.executemany(
            "INSERT INTO tenant_memberships(tenant_id,user_id,role) VALUES (?,?,?)",
            [("t1", "u1", "owner"), ("t2", "u2", "owner")],
        )
        self.db.executemany(
            "INSERT INTO devices(device_id,tenant_id,owner_user_id,label,state) VALUES (?,?,?,?,?)",
            [
                ("d1", "t1", "u1", "Windows A", "active"),
                ("d2", "t2", "u2", "Windows B", "active"),
            ],
        )

    def tearDown(self) -> None:
        self.db.close()

    def test_schema_has_expected_tables_and_default_grants_none(self):
        names = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue(
            {
                "tenants",
                "users",
                "tenant_memberships",
                "devices",
                "projects",
                "tool_grants",
                "invitations",
                "login_sessions",
                "audit_events",
            }
            <= names
        )
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM tool_grants").fetchone()[0], 0
        )

    def test_cross_tenant_grants_are_rejected_by_foreign_key(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""INSERT INTO tool_grants
                (tenant_id,device_id,user_id,tool_name,granted_by_user_id)
                VALUES ('t1','d2','u1','read_file','u1')""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""INSERT INTO tool_grants
                (tenant_id,device_id,user_id,tool_name,granted_by_user_id)
                VALUES ('t1','d1','u2','read_file','u1')""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""INSERT INTO projects
                (project_id,tenant_id,device_id,display_name)
                VALUES ('p1','t1','d2','Bad project')""")

    def test_invitation_tokens_must_be_hashed_and_roles_restricted(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""INSERT INTO invitations
                (invitation_id,tenant_id,invited_email,invited_role,token_sha256,issued_by_user_id,expires_at)
                VALUES ('invite1','t1','user@example.test','owner','token-plaintext','u1',9999999999)""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """INSERT INTO invitations
                (invitation_id,tenant_id,invited_email,invited_role,token_sha256,issued_by_user_id,expires_at)
                VALUES ('invite1','t1','user@example.test','owner',?,'u1',9999999999)""",
                ("a" * 64,),
            )

    def test_tenant_and_membership_states_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE tenants SET state='superuser' WHERE tenant_id='t1'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE tenant_memberships SET state='full-access' WHERE user_id='u1'"
            )

    def test_grant_revocation_and_expiry_state_stored(self):
        self.db.execute(
            """INSERT INTO tool_grants
            (tenant_id,device_id,user_id,tool_name,granted_by_user_id,granted_at,expires_at)
            VALUES ('t1','d1','u1','read_file','u1',?,?)""",
            (NOW, NOW + 100),
        )
        row = self.db.execute(
            "SELECT expires_at,revoked_at FROM tool_grants WHERE tenant_id='t1'"
        ).fetchone()
        self.assertEqual(row, (NOW + 100, None))
        self.db.execute(
            "UPDATE tool_grants SET revoked_at=? WHERE tenant_id='t1'", (NOW + 1,)
        )
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM tool_grants WHERE revoked_at IS NULL"
            ).fetchone()[0],
            0,
        )

    def test_login_sessions_store_only_hash_and_expiry(self):
        self.db.execute(
            """INSERT INTO login_sessions(session_sha256,user_id,expires_at)
            VALUES (?,?,?)""",
            ("b" * 64, "u1", 9999999999),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""INSERT INTO login_sessions(session_sha256,user_id,expires_at)
                VALUES ('plaintext','u1',9999999999)""")


if __name__ == "__main__":
    unittest.main()
