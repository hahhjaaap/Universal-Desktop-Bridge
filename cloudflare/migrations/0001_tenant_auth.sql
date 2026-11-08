-- P0-C: staging-only multi-tenant identity/authorization model.
-- No default tool grants are created by this migration.
-- Identity is issuer + immutable subject from a verified token, never email alone.

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'suspended', 'deleted')),
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY NOT NULL,
  issuer TEXT NOT NULL,
  subject TEXT NOT NULL,
  email TEXT,
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'disabled')),
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
  UNIQUE (issuer, subject)
);

CREATE TABLE IF NOT EXISTS tenant_memberships (
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'suspended', 'revoked')),
  joined_at INTEGER NOT NULL DEFAULT (unixepoch()),
  PRIMARY KEY (tenant_id, user_id),
  FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_memberships_user_state ON tenant_memberships(user_id, state);

CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY NOT NULL,
  tenant_id TEXT NOT NULL,
  owner_user_id TEXT NOT NULL,
  label TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'active', 'disabled', 'revoked')),
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  paired_at INTEGER,
  revoked_at INTEGER,
  UNIQUE (tenant_id, device_id),
  FOREIGN KEY (tenant_id, owner_user_id)
    REFERENCES tenant_memberships(tenant_id, user_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_devices_tenant_state ON devices(tenant_id, state);

CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY NOT NULL,
  tenant_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  -- A fingerprint, not an absolute filesystem path or file contents.
  root_fingerprint TEXT,
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'archived')),
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  UNIQUE (tenant_id, project_id),
  FOREIGN KEY (tenant_id, device_id)
    REFERENCES devices(tenant_id, device_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_projects_device ON projects(tenant_id, device_id, state);

CREATE TABLE IF NOT EXISTS tool_grants (
  tenant_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  granted_by_user_id TEXT NOT NULL,
  granted_at INTEGER NOT NULL DEFAULT (unixepoch()),
  expires_at INTEGER,
  revoked_at INTEGER,
  PRIMARY KEY (tenant_id, device_id, user_id, tool_name),
  FOREIGN KEY (tenant_id, device_id)
    REFERENCES devices(tenant_id, device_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, user_id)
    REFERENCES tenant_memberships(tenant_id, user_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, granted_by_user_id)
    REFERENCES tenant_memberships(tenant_id, user_id) ON DELETE RESTRICT,
  CHECK (length(tool_name) BETWEEN 1 AND 96),
  CHECK (expires_at IS NULL OR expires_at > granted_at)
);
CREATE INDEX IF NOT EXISTS idx_grants_user_device ON tool_grants(tenant_id, user_id, device_id);

CREATE TABLE IF NOT EXISTS invitations (
  invitation_id TEXT PRIMARY KEY NOT NULL,
  tenant_id TEXT NOT NULL,
  invited_email TEXT NOT NULL,
  invited_role TEXT NOT NULL CHECK (invited_role IN ('admin', 'member', 'viewer')),
  -- Store a one-way hash only, never a plaintext invitation token.
  token_sha256 TEXT NOT NULL UNIQUE CHECK (length(token_sha256) = 64 AND token_sha256 NOT GLOB '*[^0-9a-f]*'),
  issued_by_user_id TEXT NOT NULL,
  issued_at INTEGER NOT NULL DEFAULT (unixepoch()),
  expires_at INTEGER NOT NULL,
  accepted_by_user_id TEXT,
  accepted_at INTEGER,
  revoked_at INTEGER,
  FOREIGN KEY (tenant_id, issued_by_user_id)
    REFERENCES tenant_memberships(tenant_id, user_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, accepted_by_user_id)
    REFERENCES tenant_memberships(tenant_id, user_id) ON DELETE RESTRICT,
  CHECK (expires_at > issued_at),
  CHECK ((accepted_at IS NULL) = (accepted_by_user_id IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_invitations_tenant_expires ON invitations(tenant_id, expires_at);

CREATE TABLE IF NOT EXISTS login_sessions (
  session_sha256 TEXT PRIMARY KEY NOT NULL CHECK (length(session_sha256) = 64 AND session_sha256 NOT GLOB '*[^0-9a-f]*'),
  user_id TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  expires_at INTEGER NOT NULL,
  revoked_at INTEGER,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT,
  CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_expires ON login_sessions(user_id, expires_at);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY NOT NULL,
  tenant_id TEXT NOT NULL,
  actor_user_id TEXT,
  device_id TEXT,
  action TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('allowed', 'denied', 'success', 'failure')),
  -- No request payloads, file contents, credentials, or token values.
  occurred_at INTEGER NOT NULL DEFAULT (unixepoch()),
  FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
  FOREIGN KEY (actor_user_id) REFERENCES users(user_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_events(tenant_id, occurred_at);
