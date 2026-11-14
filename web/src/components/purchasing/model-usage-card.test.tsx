import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import type { ModelUsage } from "@/api/types";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

const TITLE = "The Buyer agent runs on Nemotron 3.5 Super VL";
const NOTE =
  "Counted by the gateway from each run; a run from before the meter has no count.";
const usage: ModelUsage = {
  model: "nemotron-3.5-super-vl",
  runs: 14,
  runsWithoutUsage: 5,
  modelCalls: 63,
  promptTokens: 371250,
  completionTokens: 16470,
  modelSeconds: 345.66,
};

const withUsage = (getModelUsage: () => Promise<ModelUsage>) =>
  Object.assign(createMockApi(), { getModelUsage });

/** The card: the About section that holds the title. */
async function card() {
  const heading = await screen.findByRole("heading", { level: 2, name: TITLE });
  return within(heading.closest("section")!);
}

describe("the model usage card on the About page", () => {
  beforeEach(() => localStorage.clear());

  it("shows the counted runs, the model calls, the tokens and the seconds", async () => {
    renderApp(
      "/about",
      withUsage(async () => usage),
    );
    const view = await card();
    const shown = Object.fromEntries(
      (await view.findAllByRole("term")).map((term) => [
        term.textContent,
        term.nextElementSibling?.textContent,
      ]),
    );
    expect(shown).toEqual({
      // 14 runs, 5 of them without a count.
      "Runs counted": "9",
      "Model calls": "63",
      "Prompt tokens": "371,250",
      "Completion tokens": "16,470",
      "Model seconds": "345.7",
    });
    expect(view.getByText(NOTE)).toBeInTheDocument();
    expect(view.queryByText("No runs counted yet")).not.toBeInTheDocument();
  });

  it("shows the mock's sample numbers by default", async () => {
    renderApp("/about");
    const view = await card();
    expect((await view.findAllByRole("term")).length).toBe(5);
  });

  it.each([
    [
      "every count is zero",
      {
        ...usage,
        runs: 0,
        runsWithoutUsage: 0,
        modelCalls: 0,
        promptTokens: 0,
        completionTokens: 0,
        modelSeconds: 0,
      },
    ],
    [
      "every run is from before the meter",
      {
        ...usage,
        runs: 3,
        runsWithoutUsage: 3,
        modelCalls: 0,
        promptTokens: 0,
        completionTokens: 0,
        modelSeconds: 0,
      },
    ],
  ])("hides the numbers when %s", async (_, zero) => {
    renderApp(
      "/about",
      withUsage(async () => zero),
    );
    const view = await card();
    expect(await view.findByText("No runs counted yet")).toBeInTheDocument();
    expect(view.queryAllByRole("term")).toEqual([]);
    expect(view.getByText(NOTE)).toBeInTheDocument();
  });

  it("hides the numbers when the call fails, and the page still shows", async () => {
    renderApp(
      "/about",
      withUsage(async () => {
        throw new ApiError(
          "GATEWAY_UNREACHABLE",
          "The gateway did not answer.",
        );
      }),
    );
    const view = await card();
    expect(await view.findByText("No runs counted yet")).toBeInTheDocument();
    expect(view.queryAllByRole("term")).toEqual([]);
    expect(
      view.queryByText("The gateway did not answer."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Trust rules" }),
    ).toBeInTheDocument();
  });
});
