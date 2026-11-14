import { describe, expect, it } from "vitest";

import { randomHex } from "@/lib/random-id";

describe("randomHex", () => {
  it("gives a different id every call, even in the same millisecond", () => {
    const ids = new Set(Array.from({ length: 200 }, () => randomHex()));
    expect(ids.size).toBe(200);
  });

  it("is hex of the asked length", () => {
    expect(randomHex(4)).toMatch(/^[0-9a-f]{8}$/);
  });
});
