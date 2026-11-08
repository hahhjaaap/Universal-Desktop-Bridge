import assert from 'node:assert/strict';
import test from 'node:test';
import { authorizedDeviceTools, authorizedDevices, validIdentity } from '../src/tenant-store.js';

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
