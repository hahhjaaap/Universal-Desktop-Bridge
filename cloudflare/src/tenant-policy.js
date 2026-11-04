// Optional strict owner/tenant/device policy for invite-only multi-user pilots.
// No API here enrolls users, grants rights or reassigns an existing device.
// Authentication remains in oauth.js / access.js; this only narrows capabilities.
import { READ_TOOLS } from "./read-tools.js";

const DEVICE = /^[a-f0-9]{32}$/;
const TENANT = /^[a-z0-9][a-z0-9-]{0,62}$/;
const MAX_POLICY = 65536;

function object(value, allowed, required = allowed) {
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).every((key) => allowed.includes(key)) &&
    required.every((key) => Object.hasOwn(value, key));
}

function list(value, max, min = 1) {
  return Array.isArray(value) && value.length >= min && value.length <= max;
}

function principal(value) {
  return typeof value === "string" && value.length > 0 &&
    value.length <= 200 && value.trim() === value && !/[\x00-\x1f]/.test(value);
}

function unique(values) {
  return new Set(values).size === values.length;
}

function validTools(tools) {
  return list(tools, READ_TOOLS.length) && unique(tools) &&
    tools.every((tool) => typeof tool === "string" && READ_TOOLS.includes(tool));
}

// A single unrecognized field, repeated device ID or malformed entry
// invalidates the entire policy; a bad tenant cannot be bypassed by
// silently falling back to the old UDB_DEVICE_GRANTS secret.
export function parseTenantPolicy(raw) {
  if (typeof raw !== "string" || raw.length === 0 ||
      raw.length > MAX_POLICY) return null;
  let policy;
  try { policy = JSON.parse(raw); }
  catch { return null; }
  if (!object(policy, ["version", "tenants"]) || policy.version !== 1 ||
      !list(policy.tenants, 32)) return null;
  const tenantIds = new Set();
  const registeredDevices = new Set();
  for (const tenant of policy.tenants) {
    if (!object(tenant, ["id", "owners", "members", "devices"]) ||
        typeof tenant.id !== "string" || !TENANT.test(tenant.id) ||
        tenantIds.has(tenant.id) ||
        !list(tenant.members, 64) ||
        !tenant.members.every(principal) || !unique(tenant.members) ||
        !list(tenant.owners, 32) ||
        !tenant.owners.every((owner) => principal(owner) &&
          tenant.members.includes(owner)) || !unique(tenant.owners) ||
        !list(tenant.devices, 64, 0)) return null;
    tenantIds.add(tenant.id);
    for (const device of tenant.devices) {
      if (!object(device, ["id", "grants"]) || typeof device.id !== "string" ||
          !DEVICE.test(device.id) || registeredDevices.has(device.id) ||
          !list(device.grants, 64, 0)) return null;
      registeredDevices.add(device.id);
      const subjects = new Set();
      for (const grant of device.grants) {
        if (!object(grant, ["subject", "tools"]) ||
            !principal(grant.subject) ||
            !tenant.members.includes(grant.subject) ||
            subjects.has(grant.subject) || !validTools(grant.tools))
          return null;
        subjects.add(grant.subject);
      }
    }
  }
  return policy;
}

// Only explicitly provisioned, authenticated subjects on a device belonging
// to exactly one tenant can use the owner's named read tools. No wildcards.
// A different subject, device or revocation update returns zero capabilities.
export function tenantDeviceGrant(raw, deviceId, subject) {
  if (!DEVICE.test(deviceId) || !principal(subject)) return [];
  const policy = parseTenantPolicy(raw);
  if (!policy) return [];
  for (const tenant of policy.tenants) {
    const device = tenant.devices.find((candidate) => candidate.id === deviceId);
    if (!device || !tenant.members.includes(subject)) continue;
    const grant = device.grants.find((item) => item.subject === subject);
    return grant ? [...grant.tools] : [];
  }
  return [];
}
