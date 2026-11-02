// Only short-lived, administrator-issued device invitations are accepted.
// Pairing codes never grant local Windows access and are not OAuth sessions.
export const PAIRING_TTL_MS = 10 * 60 * 1000;

export async function newPairing() {
  const device_id = crypto.randomUUID().replaceAll("-", "");
  const random = new Uint8Array(32);
  crypto.getRandomValues(random);
  const pairing_code = Array.from(random,
    (value) => value.toString(16).padStart(2, "0")).join("");
  const bytes = new TextEncoder().encode(pairing_code);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const pairing_token_sha256 = Array.from(new Uint8Array(digest),
    (value) => value.toString(16).padStart(2, "0")).join("");
  return { device_id, pairing_code, pairing_token_sha256 };
}
