import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { configure, getConfig, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { priceListSample } from "@/api/mock-price-list";
import { ApiError } from "@/api/types";
import { FIELD_TEXT, REASON_TEXT } from "@/components/purchasing/price-list-photo";
import { collectFinnishDictionaries } from "@/lib/i18n";
import { renderApp } from "@/test/render";

// jsdom has no canvas: the photo goes to the Api as it is. lib/shelf-photo.test.ts covers the sizes.
vi.mock("@/lib/shelf-photo", async (original) => ({
  ...(await original<typeof import("@/lib/shelf-photo")>()),
  downscalePhoto: async (file: Blob) => file,
}));

const PHOTO = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "list.png", { type: "image/png" });

/** A mock Api that answers the sample at once, so the tests wait for no timer. */
function quickApi() {
  const api = createMockApi();
  const read = vi.spyOn(api, "readPriceListPhoto").mockImplementation(async (supplierId) => priceListSample(supplierId));
  const save = vi.spyOn(api, "saveOwnProduct");
  return { api, read, save };
}

async function upload(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("heading", { name: "Töölö Bakery" });
  await user.upload(screen.getByLabelText("Choose a photo of the price list of Töölö Bakery"), PHOTO);
  return within(await screen.findByRole("dialog", { name: "Price list of Töölö Bakery" }));
}

function row(dialog: ReturnType<typeof within>, name: string) {
  return within(dialog.getByRole("group", { name }));
}

describe("SuppliersPage: add own products from a photo of the price list", () => {
  let asyncUtilTimeout: number;
  beforeAll(() => {
    asyncUtilTimeout = getConfig().asyncUtilTimeout;
    configure({ asyncUtilTimeout: 10_000 });
  });
  afterAll(() => configure({ asyncUtilTimeout }));
  beforeEach(() => localStorage.clear());

  it("shows the button for manual and CSV suppliers only, with the back camera", async () => {
    renderApp("/suppliers", createMockApi());
    const bakery = (await screen.findByRole("heading", { name: "Töölö Bakery" })).closest("[data-slot=card]");
    const valio = screen.getByRole("heading", { name: "Valio Aimo" }).closest("[data-slot=card]");
    const fish = screen.getByRole("heading", { name: "Hakaniemi Fish" }).closest("[data-slot=card]");
    expect(within(bakery as HTMLElement).getByRole("button", { name: "Add from a photo of the price list" })).toBeEnabled();
    expect(within(fish as HTMLElement).getByRole("button", { name: "Add from a photo of the price list" })).toBeEnabled();
    expect(within(valio as HTMLElement).queryByRole("button", { name: "Add from a photo of the price list" })).toBeNull();
    const camera = screen.getByLabelText("Take a photo of the price list of Töölö Bakery");
    expect(camera).toHaveAttribute("capture", "environment");
    expect(camera).toHaveAttribute("accept", "image/*");
  });

  it("shows the rows, marks the please-check rows with the reason, and keeps their empty fields empty", async () => {
    const user = userEvent.setup();
    const { api, read, save } = quickApi();
    renderApp("/suppliers", api);
    const dialog = await upload(user);

    await waitFor(() =>
      expect(dialog.getByRole("status")).toHaveTextContent(
        "Read by Nemotron 3.5 Super VL in 5.2 s: 6 rows, 2 to check.",
      ),
    );
    expect(read).toHaveBeenCalledWith("SUP-BAKERY", PHOTO, "human");
    expect(dialog.getAllByTestId("price-list-row")).toHaveLength(6);

    const seeds = row(dialog, "Seed rolls");
    expect(dialog.getByRole("group", { name: "Seed rolls" })).toHaveAttribute("data-check", "true");
    expect(seeds.getByText("Please check")).toBeInTheDocument();
    expect(seeds.getByText(REASON_TEXT.PRICE_UNIT_MISSING)).toBeInTheDocument();
    expect(seeds.getByLabelText("Price (EUR)")).toHaveValue("");
    expect(seeds.getByLabelText("Unit")).toHaveValue("");
    expect(seeds.getByRole("checkbox", { name: "Save Seed rolls" })).not.toBeChecked();
    expect(seeds.getByText("Fill in before saving: price, unit.")).toBeInTheDocument();

    const croissant = row(dialog, "Butter croissant");
    expect(croissant.getByText(REASON_TEXT.PACK_UNCLEAR)).toBeInTheDocument();
    expect(croissant.getByLabelText("Pack size")).toHaveValue("");

    // A clean new row starts ticked, a match never does.
    expect(row(dialog, "Oat sourdough loaf").getByRole("checkbox")).toBeChecked();
    expect(row(dialog, "Oat sourdough loaf").getByText("New")).toBeInTheDocument();
    const rye = row(dialog, "Rye bread loaf");
    expect(rye.getByText("Price changed")).toBeInTheDocument();
    expect(rye.getByText("€4.20")).toBeInTheDocument();
    expect(rye.getByText("€4.40")).toBeInTheDocument();
    expect(rye.getByRole("checkbox")).not.toBeChecked();
    expect(row(dialog, "Cinnamon bun").getByRole("checkbox")).toBeDisabled();

    // Nothing is sent before the person presses save.
    expect(save).not.toHaveBeenCalled();
  });

  it("saves only the ticked, complete rows, one at a time, and says per row what happened", async () => {
    const user = userEvent.setup();
    const { api, save } = quickApi();
    renderApp("/suppliers", api);
    const dialog = await upload(user);
    await dialog.findAllByTestId("price-list-row");

    // Untick Karelian pies; tick Seed rolls but leave it incomplete; fill and tick the croissant.
    await user.click(row(dialog, "Karelian pies").getByRole("checkbox"));
    await user.click(row(dialog, "Seed rolls").getByRole("checkbox"));
    const croissant = row(dialog, "Butter croissant");
    await user.type(croissant.getByLabelText("Pack size"), "0.06");
    await user.selectOptions(croissant.getByLabelText("Pack measure"), "KG");
    await user.click(croissant.getByRole("checkbox"));
    // Tick the price change.
    await user.click(row(dialog, "Rye bread loaf").getByRole("checkbox"));

    await user.click(dialog.getByRole("button", { name: "Save checked rows" }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(3));
    expect(save.mock.calls.map(([product]) => product.name)).toEqual(["Rye bread loaf", "Oat sourdough loaf", "Butter croissant"]);
    expect(save.mock.calls[0][0]).toMatchObject({ id: "OWN-RYE", priceEur: 4.4, priceSource: "price_list_photo" });
    // The change keeps the stored allergens; it changes the price only.
    expect(save.mock.calls[0][0].allergens).toEqual([{ code: "AW", name: "Gluten cereals", presence: "CONTAINS" }]);
    expect(save.mock.calls[1][0]).toEqual({
      name: "Oat sourdough loaf",
      unit: "ST",
      packSize: 0.75,
      baseUnit: "KG",
      priceEur: 5.2,
      supplierId: "SUP-BAKERY",
      allergens: null,
      priceSource: "price_list_photo",
    });
    expect(save.mock.calls[2][0]).toMatchObject({ name: "Butter croissant", packSize: 0.06, baseUnit: "KG" });
    expect(save.mock.calls.some(([product]) => product.name === "Seed rolls" || product.name === "Karelian pies")).toBe(false);

    expect(await row(dialog, "Rye bread loaf").findByText("Saved: the new price of Rye bread loaf.")).toBeInTheDocument();
    expect(row(dialog, "Oat sourdough loaf").getByText("Saved as a new product.")).toBeInTheDocument();
    expect(row(dialog, "Seed rolls").getByRole("alert")).toHaveTextContent("Not saved. Fill in: price, unit.");
    const stored = await api.listOwnProducts();
    expect(stored.find((product) => product.id === "OWN-RYE")?.priceEur).toBe(4.4);
    expect(stored.some((product) => product.name === "Oat sourdough loaf")).toBe(true);
    expect(stored.some((product) => product.name === "Karelian pies")).toBe(false);
  });

  it("shows a refused row's own error and goes on with the next row", async () => {
    const user = userEvent.setup();
    const { api, save } = quickApi();
    save.mockImplementationOnce(async () => {
      throw new ApiError("INVALID", "The gateway refused the unit.");
    });
    renderApp("/suppliers", api);
    const dialog = await upload(user);
    await dialog.findAllByTestId("price-list-row");
    await user.click(dialog.getByRole("button", { name: "Save checked rows" }));

    expect(await row(dialog, "Oat sourdough loaf").findByRole("alert")).toHaveTextContent(
      "Not saved: The gateway refused the unit.",
    );
    expect(await row(dialog, "Karelian pies").findByText("Saved as a new product.")).toBeInTheDocument();
  });

  it.each([
    [new ApiError("PRICE_LIST_BUSY", "busy", {}, 429), "Another price list is being read for this kitchen. Wait a moment, then try again."],
    [new ApiError("VISION_TIMEOUT", "late", {}, 504), "Nemotron is not answering right now."],
    [new ApiError("VISION_REPLY_INVALID", "bad", {}, 502), "Nemotron's answer could not be used."],
    [
      new ApiError("SUPPLIER_HAS_API", "api", {}, 422),
      "This supplier sends its prices through its own system, so a photo of a price list is not needed.",
    ],
  ])("says %s in plain words and saves nothing", async (problem, text) => {
    const user = userEvent.setup();
    const { api, read, save } = quickApi();
    read.mockRejectedValueOnce(problem);
    renderApp("/suppliers", api);
    const dialog = await upload(user);
    expect(await dialog.findByRole("alert")).toHaveTextContent(text);
    expect(dialog.queryByRole("button", { name: "Save checked rows" })).toBeNull();
    expect(save).not.toHaveBeenCalled();
  });

  it("has a Finnish entry for every text it shows", () => {
    const files = import.meta.glob("../i18n/fi/*.ts", { eager: true }) as Record<string, { default: Record<string, string> }>;
    const dictionary = collectFinnishDictionaries(files);
    const source = readFileSync(resolve(process.cwd(), "src/components/purchasing/price-list-photo.tsx"), "utf8");
    const texts = [
      ...[...source.matchAll(/\bt\(\s*"((?:\\.|[^"\\])*)"/g)].map((match) => JSON.parse(`"${match[1]}"`) as string),
      ...Object.values(REASON_TEXT),
      ...Object.values(FIELD_TEXT),
    ];
    expect(texts.filter((text) => !Object.prototype.hasOwnProperty.call(dictionary, text))).toEqual([]);
  });
});
