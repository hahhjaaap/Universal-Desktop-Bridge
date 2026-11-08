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
