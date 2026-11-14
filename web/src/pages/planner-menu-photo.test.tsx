import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { menuPhotoSample } from "@/api/mock-menu-photo";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

// jsdom has no canvas: the photo goes to the Api as it is. lib/shelf-photo.test.ts covers the sizes.
vi.mock("@/lib/shelf-photo", async (original) => ({
  ...(await original<typeof import("@/lib/shelf-photo")>()),
  downscalePhoto: async (file: Blob) => file,
}));

const PHOTO = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "menu.png", { type: "image/png" });

/** Fixes "today" for the page; only `Date` is faked, so user events and timers still run. */
function onDay(date: string) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(`${date}T12:00:00Z`));
}

async function panel() {
  const heading = await screen.findByRole("heading", { name: "Plan from a menu photo" });
  return within(heading.closest("section") as HTMLElement);
}

async function choosePhoto(user: ReturnType<typeof userEvent.setup>) {
  const section = await panel();
  await user.upload(section.getByLabelText("Choose a photo of the menu"), PHOTO);
  return section;
}

describe("PlannerPage: plan from a menu photo", () => {
  beforeEach(() => {
    localStorage.clear();
    // Wednesday of week 47: the planner opens on week 48, 23 to 29 November.
    onDay("2026-11-18");
  });
  afterEach(() => vi.useRealTimers());

  it("opens the back camera on a phone, and the file button takes any image", async () => {
    renderApp("/planner", createMockApi());
    const section = await panel();
    expect(section.getByRole("button", { name: "Take a photo" })).toBeEnabled();
    expect(section.getByRole("button", { name: "Choose a file" })).toBeEnabled();
    expect(section.getByLabelText("Take a photo of the menu")).toHaveAttribute("capture", "environment");
    expect(section.getByLabelText("Take a photo of the menu")).toHaveAttribute("accept", "image/*");
    expect(section.getByLabelText("Choose a photo of the menu")).not.toHaveAttribute("capture");
  });

  it("shows the dishes per day and points to the waiting proposal in the inbox", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const read = vi.spyOn(api, "readMenuPhoto");
    renderApp("/planner", api);
    const section = await choosePhoto(user);

    expect(section.getByRole("status")).toHaveTextContent("Nemotron 3.5 Super VL is reading the menu.");
    await waitFor(
      () =>
        expect(section.getByRole("status")).toHaveTextContent(
          "Nemotron 3.5 Super VL read 5 dishes in 6.1 s: 4 matched to your recipes, 1 not known.",
        ),
      { timeout: 3000 },
    );
    expect(read).toHaveBeenCalledWith(PHOTO, { from: "2026-11-23", to: "2026-11-29", requestedDate: "2026-11-23" }, "human");
    expect(section.getAllByTestId("menu-photo-dish")).toHaveLength(5);
    expect(section.getAllByText("Matched to recipe Salmon soup.")).toHaveLength(2);
    expect(section.getAllByText("Matched to recipe Rice pudding.")).toHaveLength(2);
    expect(section.getByRole("heading", { name: /Monday/ })).toBeInTheDocument();
    expect(section.getByRole("link", { name: "Orders > To approve" })).toHaveAttribute("href", "/approvals");
    expect(section.getByRole("status")).toHaveTextContent("A person approves it there. Nothing is ordered from this page.");
  });

  it("lists a dish that matches no recipe as not known, with a link to the recipes", async () => {
    const user = userEvent.setup();
    renderApp("/planner", createMockApi());
    const section = await choosePhoto(user);
    const stew = (await section.findByText("“Reindeer stew”", {}, { timeout: 3000 })).closest("li") as HTMLElement;
    expect(stew).toHaveTextContent("Not known: add it to your recipes, or plan this day by hand.");
    expect(stew).not.toHaveTextContent("Matched to recipe");
    expect(within(stew).getByRole("link", { name: "recipes" })).toHaveAttribute("href", "/products");
  });

  it("says in plain words when the model is not answering, and shows no dish", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.readMenuPhoto = async () => {
      throw new ApiError("VISION_UNAVAILABLE", "upstream 502", {}, 503);
    };
    renderApp("/planner", api);
    const section = await choosePhoto(user);
    expect(await section.findByRole("alert")).toHaveTextContent(
      "The model is not answering right now. Plan the week by hand or try again later.",
    );
    expect(section.queryAllByTestId("menu-photo-dish")).toHaveLength(0);
    expect(section.getByRole("button", { name: "Choose a file" })).toBeEnabled();
  });

  it("says another menu photo is being read on MENU_PHOTO_BUSY, not the rate limit", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.readMenuPhoto = async () => {
      throw new ApiError("MENU_PHOTO_BUSY", "Another menu photo is being read.", {}, 429);
    };
    renderApp("/planner", api);
    const section = await choosePhoto(user);
    expect(await section.findByRole("alert")).toHaveTextContent("Another menu photo is being read. Wait for it, then try again.");
  });

  it("shows the dishes read when none matched a recipe", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const dishes = menuPhotoSample("2026-11-23", "2026-11-29").dishes.slice(4);
    api.readMenuPhoto = async () => {
      throw new ApiError("NOTHING_MATCHED", "no dish matched", { dishes }, 422);
    };
    renderApp("/planner", api);
    const section = await choosePhoto(user);
    expect(await section.findByRole("alert")).toHaveTextContent("No dish on the photo matches one of your recipes.");
    expect(section.getByText("“Reindeer stew”")).toBeInTheDocument();
  });

  it("orders nothing: no order or approve button, and no proposal call from the page", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const approve = vi.spyOn(api, "approve");
    const propose = vi.spyOn(api, "proposeOrderForPlan");
    renderApp("/planner", api);
    const section = await choosePhoto(user);
    await section.findByText("“Reindeer stew”", {}, { timeout: 3000 });
    expect(section.getAllByRole("button").map((button) => button.textContent)).toEqual(["Take a photo", "Choose a file"]);
    expect(section.queryByRole("button", { name: /order|approve|send/i })).toBeNull();
    expect(approve).not.toHaveBeenCalled();
    expect(propose).not.toHaveBeenCalled();
  });

  it("is switched off for a week in the past", async () => {
    renderApp("/planner?week=2026-W40", createMockApi());
    const section = await panel();
    expect(section.getByRole("button", { name: "Take a photo" })).toBeDisabled();
    expect(section.getByRole("button", { name: "Choose a file" })).toBeDisabled();
  });
});
