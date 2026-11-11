import assert from "node:assert/strict";
import test from "node:test";
import { companionAnnotations } from "../src/companion-tools.js";

test("Companion metadata does not label host mutations as read-only", () => {
  for (const name of ["file_write", "file_replace", "file_operation",
    "terminal_start", "terminal_interact", "system_process_terminate"]) {
    const annotations = companionAnnotations(name);
    assert.equal(annotations?.readOnlyHint, false, name);
    assert.equal(annotations?.destructiveHint, true, name);
  }
  for (const name of ["file_read", "file_list", "file_stat",
    "terminal_read", "system_process_list"]) {
    const annotations = companionAnnotations(name);
    assert.equal(annotations?.readOnlyHint, true, name);
    assert.equal(annotations?.destructiveHint, false, name);
  }
  assert.equal(companionAnnotations("terminal_start")?.openWorldHint, true);
  assert.equal(companionAnnotations("file_mkdir")?.readOnlyHint, false);
  assert.equal(companionAnnotations("not-a-companion-tool"), undefined);
});
