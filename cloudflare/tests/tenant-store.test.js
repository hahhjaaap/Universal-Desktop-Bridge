import assert from 'node:assert/strict';
import test from 'node:test';
import { authorizedDeviceTools, authorizedDevices, revokeOwnedToolGrant, revokeOwnedDevice, validIdentity } from '../src/tenant-store.js';

const actor = { issuer: 'https://idp.example.test', subject: 'account-001' };
const params = { tenantId: 'tenant_a', deviceId: 'device_a', identity: actor,
  catalogNames: new Set(['bridge_status', 'read_file']), now: 1000 };

function fakeDb(rows, fail = false) {
  let args, sql;
  return {
    get args() { return args; }, get sql() { return sql; },
    prepare(query) { sql = query; return { bind(...a) { args = a; return {
      async all() { if (fail) throw new Error('offline'); return { success: true, results: rows }; },
    }; } }; },
  };
}

test('requires verified-style issuer/subject, never email-only input', () => {
  assert.equal(validIdentity(actor), true);
  assert.equal(validIdentity({ email: 'owner@example.test' }), false);
  assert.equal(validIdentity({ issuer: 'http://insecure', subject: 'x' }), false);
  assert.equal(validIdentity({ issuer: actor.issuer, subject: '' }), false);
});

test('returns only known, explicitly granted tools in deterministic order', async () => {
  const db = fakeDb([{tool_name:'bridge_status'}, {tool_name:'unknown_tool'}, {tool_name:'read_file'}]);
  assert.deepEqual(await authorizedDeviceTools(db, params), ['bridge_status', 'read_file']);
  assert.deepEqual(db.args, ['tenant_a','device_a',actor.issuer,actor.subject,1000]);
  for (const predicate of ["t.state = 'active'", "d.state = 'active'", "m.state = 'active'",
    "u.state = 'active'", "g.revoked_at IS NULL", "g.expires_at > ?5"]) {
    assert.ok(db.sql.includes(predicate), predicate);
  }
});

test('missing catalog or malformed request and D1 outage fail closed', async () => {
  assert.deepEqual(await authorizedDeviceTools(fakeDb([]), {...params,catalogNames:new Set()}), []);
  assert.deepEqual(await authorizedDeviceTools(fakeDb([]), {...params,identity:{email:'x'}}), []);
  assert.deepEqual(await authorizedDeviceTools(fakeDb([]), {...params,tenantId:'tenant_a OR 1=1'}), []);
  assert.deepEqual(await authorizedDeviceTools(fakeDb([]), {...params,deviceId:'../other'}), []);
  assert.deepEqual(await authorizedDeviceTools(fakeDb([]), {...params,now:NaN}), []);
  assert.deepEqual(await authorizedDeviceTools(fakeDb([],true),params), []);
});

test('device listing only reveals active devices with current grants', async () => {
  const db = fakeDb([{device_id:'device_a',label:'Test Windows'}]);
  assert.deepEqual(await authorizedDevices(db,{tenantId:'tenant_a',identity:actor,now:456}),
    [{deviceId:'device_a',label:'Test Windows'}]);
  assert.ok(db.sql.includes('EXISTS'));
  assert.deepEqual(await authorizedDevices(fakeDb([],true),{tenantId:'tenant_a',identity:actor}), []);
});


function writeDb({ changes = 1, failure = false } = {}) {
  let sql, bindings, called = 0;
  return {
    get sql() { return sql; }, get bindings() { return bindings; },
    get called() { return called; },
    prepare(query) {
      sql = query; called++;
      return { bind(...items) {
        bindings = items;
        return { async run() {
          if (failure) throw new Error('D1 unavailable');
          return { success: true, meta: { changes } };
        } };
      } };
    },
  };
}

test('owner-scoped revocation uses an atomic, parameterized D1 update', async () => {
  const db = writeDb();
  assert.equal(await revokeOwnedToolGrant(db, {
    tenantId: 'tenant_a', deviceId: 'device_a',
    ownerIdentity: actor,
    targetIdentity: { issuer: actor.issuer, subject: 'collaborator-2' },
    toolName: 'read_file', catalogNames: params.catalogNames, now: 1200,
  }), true);
  assert.deepEqual(db.bindings, [
    1200, 'tenant_a', 'device_a', 'read_file',
    actor.issuer, 'collaborator-2', actor.issuer, actor.subject,
  ]);
  for (const condition of [
    'revoked_at IS NULL', "d.state = 'active'", "t.state = 'active'",
    "om.state = 'active'", "m.state = 'active'",
    'd.owner_user_id', 'o.issuer = ?7', 'o.subject = ?8',
  ]) assert.ok(db.sql.includes(condition), condition);
});

test('revocation never creates grants and returns false if target was already revoked', async () => {
  assert.equal(await revokeOwnedToolGrant(writeDb({changes:0}), {
    ...params, ownerIdentity:actor, targetIdentity:actor, toolName:'read_file',
  }), false);
  const unavailable = writeDb({ failure:true });
  assert.equal(await revokeOwnedToolGrant(unavailable, {
    ...params, ownerIdentity:actor, targetIdentity:actor, toolName:'read_file',
  }), false);
});

test('revocation is fail-closed on malformed devices, identities, and tool names', async () => {
  const db = writeDb();
  for (const inputs of [
    { ...params, deviceId: '../device', ownerIdentity:actor,
      targetIdentity:actor, toolName:'read_file' },
    { ...params, ownerIdentity:{email:'forge@example.test'},
      targetIdentity:actor, toolName:'read_file' },
    { ...params, ownerIdentity:actor, targetIdentity:actor, toolName:'computer_desktop' },
    { ...params, ownerIdentity:actor, targetIdentity:actor, toolName:'read_file',
      catalogNames:new Set() },
    { ...params, ownerIdentity:actor, targetIdentity:actor, toolName:'read_file',
      now:0 },
  ]) assert.equal(await revokeOwnedToolGrant(db, inputs), false);
  assert.equal(db.called, 0);
});

test('device revocation is owner-scoped, irreversible via helper, and fail-closed', async () => {
  const db = writeDb();
  assert.equal(await revokeOwnedDevice(db, {
    tenantId:'tenant_a', deviceId:'device_a', ownerIdentity:actor, now:2000,
  }), true);
  assert.deepEqual(db.bindings, [2000, 'tenant_a', 'device_a',
    actor.issuer, actor.subject]);
  for (const condition of [
    "SET state = 'revoked'", "state = 'active'", 'revoked_at = ?1',
    'm.user_id = devices.owner_user_id', "t.state = 'active'",
    "m.state = 'active'", 'u.issuer = ?4', 'u.subject = ?5',
  ]) assert.ok(db.sql.includes(condition), condition);
  assert.equal(await revokeOwnedDevice(writeDb({changes:0}), {
    tenantId:'tenant_a', deviceId:'device_a', ownerIdentity:actor, now:2000,
  }), false);
  assert.equal(await revokeOwnedDevice(writeDb({failure:true}), {
    tenantId:'tenant_a', deviceId:'device_a', ownerIdentity:actor, now:2000,
  }), false);
  assert.equal(await revokeOwnedDevice(db, {
    tenantId:'other!tenant', deviceId:'device_a', ownerIdentity:actor, now:2000,
  }), false);
});
