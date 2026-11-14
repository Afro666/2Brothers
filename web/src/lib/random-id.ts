/**
 * A random hex id. `crypto.getRandomValues`, not `randomUUID`: randomUUID exists only in a
 * secure context, and the demo may be served on a plain-HTTP address (#176, review of #597).
 */
export function randomBytes(count: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(count));
}

/** Bytes as lowercase hex, two characters per byte. */
export function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export function randomHex(bytes = 8): string {
  return toHex(randomBytes(bytes));
}
