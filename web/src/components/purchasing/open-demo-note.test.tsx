import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

const FIRST = "Open demo: everyone here is the demo approver.";
const SECOND = "Sign-in with roles (approver, chef, viewer) is built and switched off for judging.";

describe("open demo note (#1052)", () => {
  beforeEach(() => localStorage.clear());

  for (const path of ["/", "/approvals"]) {
    it(`says ${path} is the open demo when nobody is signed in`, async () => {
      renderApp(path, createMockApi());
      const note = await screen.findByTestId("open-demo-note");
      expect(note).toHaveTextContent(`${FIRST} ${SECOND}`);
      expect(note).toHaveAttribute("title", `${FIRST} ${SECOND}`);
      // One line at 390 px: the first sentence truncates, the second shows from `sm` up.
      expect(note).toHaveClass("truncate");
      expect(screen.getByText(SECOND, { exact: false })).toHaveClass("hidden", "sm:inline");
    });

    it(`shows no note on ${path} for a signed-in account`, async () => {
      const api = createMockApi();
      await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
      renderApp(path, api);
      expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
      expect(screen.queryByTestId("open-demo-note")).not.toBeInTheDocument();
    });
  }
});
