// D1 staging authorization read model. No HTTP route calls this module yet.
// Call only after cryptographic verification of an OAuth/Access identity.
// Email is display metadata, never an authorization identifier.
// All grants are opt-in and must also be checked by the Windows local owner gate.

const ID = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/;
const TOOL = /^[a-z][a-z0-9_]{0,95}$/;

export function validIdentity(identity) {
  return identity && typeof identity === 'object' &&
    typeof identity.issuer === 'string' && identity.issuer.startsWith('https://') &&
    identity.issuer.length <= 256 &&
    typeof identity.subject === 'string' && identity.subject.length > 0 &&
    identity.subject.length <= 256;
}

// Return only explicitly approved tools; invalid input and DB outages deny access.
// The caller must supply catalogNames from a *trusted* 59-tool registry (not from RPC).
export async function authorizedDeviceTools(db, {
  tenantId, deviceId, identity, catalogNames, now = Math.floor(Date.now() / 1000),
} = {}) {
  if (!db?.prepare || !ID.test(tenantId ?? '') || !ID.test(deviceId ?? '') ||
      !validIdentity(identity) || !Number.isSafeInteger(now) ||
      !(catalogNames instanceof Set) || catalogNames.size === 0) return [];
  try {
    const statement = db.prepare(`
      SELECT g.tool_name
      FROM tool_grants AS g
      INNER JOIN devices AS d
        ON d.tenant_id = g.tenant_id AND d.device_id = g.device_id
      INNER JOIN tenants AS t ON t.tenant_id = g.tenant_id
      INNER JOIN tenant_memberships AS m
        ON m.tenant_id = g.tenant_id AND m.user_id = g.user_id
      INNER JOIN users AS u ON u.user_id = m.user_id
      WHERE g.tenant_id = ?1 AND g.device_id = ?2
        AND u.issuer = ?3 AND u.subject = ?4
        AND t.state = 'active' AND d.state = 'active'
        AND m.state = 'active' AND u.state = 'active'
        AND g.revoked_at IS NULL
        AND (g.expires_at IS NULL OR g.expires_at > ?5)
      ORDER BY g.tool_name
      LIMIT 100
    `);
    const response = await statement.bind(
      tenantId, deviceId, identity.issuer, identity.subject, now,
    ).all();
    if (!response?.success || !Array.isArray(response.results)) return [];
    return response.results.map(row => row?.tool_name)
      .filter(name => typeof name === 'string' && TOOL.test(name) && catalogNames.has(name));
  } catch { return []; }
}

export async function authorizedDevices(db, { tenantId, identity, now = Math.floor(Date.now() / 1000) } = {}) {
  if (!db?.prepare || !ID.test(tenantId ?? '') || !validIdentity(identity) ||
      !Number.isSafeInteger(now)) return [];
  try {
    const response = await db.prepare(`
      SELECT d.device_id, d.label
      FROM devices d
      INNER JOIN tenants t ON t.tenant_id = d.tenant_id
      INNER JOIN tenant_memberships m ON m.tenant_id = t.tenant_id
      INNER JOIN users u ON u.user_id = m.user_id
      WHERE d.tenant_id = ?1 AND u.issuer = ?2 AND u.subject = ?3
        AND t.state = 'active' AND d.state = 'active'
        AND m.state = 'active' AND u.state = 'active'
        AND EXISTS (
          SELECT 1 FROM tool_grants g
          WHERE g.tenant_id = d.tenant_id AND g.device_id = d.device_id
            AND g.user_id = u.user_id AND g.revoked_at IS NULL
            AND (g.expires_at IS NULL OR g.expires_at > ?4)
        )
      ORDER BY d.label, d.device_id
      LIMIT 100
    `).bind(tenantId, identity.issuer, identity.subject, now).all();
    if (!response?.success || !Array.isArray(response.results)) return [];
    return response.results.map(row => ({ deviceId: row.device_id, label: row.label }));
  } catch { return []; }
}


// These operations are intentionally NOT mounted on HTTP routes. An upstream
// cryptographic verifier must construct the two identities. Revoking a device
// in D1 denies MCP authorization immediately once the D1 gate is enabled,
// but its Durable Object socket/token must ALSO be revoked by the pairing
// service. Do not expose these helpers before that integration is complete.

export async function revokeOwnedToolGrant(db, {
  tenantId, deviceId, ownerIdentity, targetIdentity, toolName,
  catalogNames, now = Math.floor(Date.now() / 1000),
} = {}) {
  if (!db?.prepare || !ID.test(tenantId ?? '') || !ID.test(deviceId ?? '') ||
      !validIdentity(ownerIdentity) || !validIdentity(targetIdentity) ||
      !TOOL.test(toolName ?? '') || !(catalogNames instanceof Set) ||
      !catalogNames.has(toolName) || !Number.isSafeInteger(now) || now <= 0) return false;
  try {
    const response = await db.prepare(`
      UPDATE tool_grants
      SET revoked_at = ?1
      WHERE tenant_id = ?2 AND device_id = ?3
        AND tool_name = ?4 AND revoked_at IS NULL
        AND user_id IN (
          SELECT u.user_id FROM users AS u
          INNER JOIN tenant_memberships AS m ON m.user_id = u.user_id
          WHERE u.issuer = ?5 AND u.subject = ?6 AND u.state = 'active'
            AND m.tenant_id = ?2 AND m.state = 'active'
        )
        AND EXISTS (
          SELECT 1 FROM devices AS d
          INNER JOIN tenants AS t ON t.tenant_id = d.tenant_id
          INNER JOIN users AS o ON o.user_id = d.owner_user_id
          INNER JOIN tenant_memberships AS om ON
            om.user_id = o.user_id AND om.tenant_id = d.tenant_id
          WHERE d.device_id = ?3 AND d.tenant_id = ?2
            AND d.state = 'active' AND t.state = 'active'
            AND om.state = 'active' AND o.state = 'active'
            AND o.issuer = ?7 AND o.subject = ?8
        )
    `).bind(
      now, tenantId, deviceId, toolName,
      targetIdentity.issuer, targetIdentity.subject,
      ownerIdentity.issuer, ownerIdentity.subject,
    ).run();
    return response?.success === true && response.meta?.changes === 1;
  } catch { return false; }
}

export async function revokeOwnedDevice(db, {
  tenantId, deviceId, ownerIdentity,
  now = Math.floor(Date.now() / 1000),
} = {}) {
  if (!db?.prepare || !ID.test(tenantId ?? '') || !ID.test(deviceId ?? '') ||
      !validIdentity(ownerIdentity) || !Number.isSafeInteger(now) ||
      now <= 0) return false;
  try {
    const response = await db.prepare(`
      UPDATE devices
      SET state = 'revoked', revoked_at = ?1
      WHERE tenant_id = ?2 AND device_id = ?3 AND state = 'active'
        AND EXISTS (
          SELECT 1 FROM tenants AS t
          INNER JOIN tenant_memberships AS m ON m.tenant_id = t.tenant_id
          INNER JOIN users AS u ON u.user_id = m.user_id
          WHERE t.tenant_id = ?2 AND t.state = 'active'
            AND m.user_id = devices.owner_user_id
            AND m.state = 'active' AND u.state = 'active'
            AND u.issuer = ?4 AND u.subject = ?5
        )
    `).bind(now, tenantId, deviceId, ownerIdentity.issuer, ownerIdentity.subject)
      .run();
    return response?.success === true && response.meta?.changes === 1;
  } catch { return false; }
}
