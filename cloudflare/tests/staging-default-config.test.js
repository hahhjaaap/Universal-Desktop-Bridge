import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("the default Wrangler commands target the single staging gateway", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url)));
  const staging = JSON.parse(readFileSync(new URL("../wrangler.staging.jsonc", import.meta.url)));
  const implicit = JSON.parse(readFileSync(new URL("../wrangler.jsonc", import.meta.url)));
  assert.deepEqual(implicit, staging, "bare Wrangler must not create another Worker");
  assert.equal(staging.name, "udb-private-relay-staging");
  for (const command of ["dev", "deploy"]) {
    const script = packageJson.scripts[command];
    assert.match(script, /--config wrangler\.staging\.jsonc(?:\s|$)/);
    assert.doesNotMatch(script, /wrangler\.jsonc(?:\s|$)/);
    if (command === "deploy") {
      assert.match(script, /--keep-vars/);
      assert.match(script, /--strict/);
    }
  }
});
