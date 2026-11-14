/**
 * A random hex id. `crypto.getRandomValues`, not `randomUUID`: randomUUID exists only in a
 * secure context, and the demo may be served on a plain-HTTP address (#176, review of #597).
 */
export function randomHex(bytes = 8): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (value) => value.toString(16).padStart(2, "0")).join("");
}
