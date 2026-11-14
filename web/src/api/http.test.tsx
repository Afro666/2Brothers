import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createHttpApi } from "@/api/http";
import { renderApp } from "@/test/render";

describe("http api", () => {
  it("has no live set and is not a thenable", () => {
    const api = createHttpApi("http://x") as unknown as Record<string, unknown>;
    expect(api.live).toBeUndefined();
    expect(api.then).toBeUndefined();
  });

  it("rejects methods with NOT_SERVED", async () => {
    await expect(createHttpApi("http://x").searchProducts({ query: "" } as never)).rejects.toMatchObject({
      code: "NOT_SERVED",
    });
  });

  it("renders /catalog with an error state instead of crashing", async () => {
    renderApp("/catalog", createHttpApi("http://x"));

    expect(await screen.findByRole("alert")).toHaveTextContent("The gateway does not serve this yet.");
  });
});
