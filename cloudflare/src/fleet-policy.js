// One canonical account-Fleet readiness policy shared by enrollment, MCP and
// Windows setup diagnostics. Feature switches alone must not claim Fleet ready.
import { accessConfig } from "./access.js";

export const fleetEnabled = env =>
  env?.UDB_ENABLE_ACCOUNT_FLEET === "true" &&
  env?.UDB_ENABLE_BROWSER_ENROLLMENT === "true" &&
  env?.UDB_ENABLE_LOCAL_TOOL_SYNC === "true" &&
  env?.UDB_TENANT_POLICY === undefined &&
  env?.UDB_AUTH_MODE === "cloudflare-access" &&
  !!accessConfig(env)?.team && !!env.DEVICES?.get;
