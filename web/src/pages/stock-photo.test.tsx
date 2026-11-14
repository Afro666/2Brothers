import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import type { Api, ShelfPhotoRead } from "@/api/types";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

// jsdom has no canvas: the photo goes to the Api as it is. lib/shelf-photo.test.ts covers the sizes.
vi.mock("@/lib/shelf-photo", async (original) => ({
  ...(await original<typeof import("@/lib/shelf-photo")>()),
  downscalePhoto: async (file: Blob) => file,
}));

const PHOTO = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "shelf.png", { type: "image/png" });
const MARK = "read from the photo by Nemotron 3.5 Super VL, check and save";

const count = (name: string) => screen.getAllByRole("textbox", { name: `${name} count in L` })[0];

async function choosePhoto(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText(/not counted: treated as unknown, not as zero/);
  await user.upload(screen.getByLabelText("Choose a photo of the shelf"), PHOTO);
}

const SAMPLE = readFileSync(resolve(process.cwd(), "public", "sample-shelf.png"));

const sampleFetch = (ok = true) =>
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    expect(String(input)).toBe("/sample-shelf.png");
    return new Response(ok ? SAMPLE : null, { status: ok ? 200 : 404 });
  }));

async function pressSample(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText(/not counted: treated as unknown, not as zero/);
  await user.click(screen.getByRole("button", { name: "Try with a sample shelf photo" }));
}

describe("StockPage: count from a photo", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("opens the back camera on a phone and takes any image", async () => {
    renderApp("/stock", createMockApi());
    await screen.findByRole("button", { name: "Count from a photo" });
    const camera = screen.getByLabelText("Take a photo of the shelf");
    expect(camera).toHaveAttribute("accept", "image/*");
    expect(camera).toHaveAttribute("capture", "environment");
    expect(screen.getByLabelText("Choose a photo of the shelf")).not.toHaveAttribute("capture");
  });

  it("fills the counted rows as suggestions and saves nothing by itself", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const before = await api.getStock();
    let saves = 0;
    const submit = api.submitStockCount;
    api.submitStockCount = async (counts, actor) => {
      saves += 1;
      return submit(counts, actor);
    };
    renderApp("/stock", api);
    await choosePhoto(user);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Nemotron 3.5 Super VL read 5 products in 2.2 s. 4 counts filled in below; 1 to count by hand. " +
          "Nothing is saved until you press Save count.",
      ),
    );
    expect(count("Arla lactose-free milk")).toHaveValue("7");
    expect(count("Valio Eila 3 % milk")).toHaveValue("6");
    expect(count("Valio Eila organic milk")).toHaveValue("4");
    expect(count("Valio Eila novobox milk")).toHaveValue("20"); // 2 boxes x 10 L
    expect(screen.getAllByText(MARK)).toHaveLength(8); // 4 products, table and phone list
    const read = within(screen.getByRole("list", { name: "What was read from the photo" }));
    expect(read.getByText("2 packs x 10 L.", { exact: false })).toBeInTheDocument();
    expect(saves).toBe(0);
    expect(await api.getStock()).toEqual(before);
  });

  it("lists a row the model was not sure of with please count and no number", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const fixture = await api.readShelfPhoto(PHOTO, "human");
    const answer: ShelfPhotoRead = {
      ...fixture,
      rows: [
        fixture.rows[0],
        { ...fixture.rows[1], kind: "PLEASE_COUNT", confidence: "low", packs: null, count: null },
        fixture.rows[4],
      ],
    };
    api.readShelfPhoto = async () => answer;
    renderApp("/stock", api);
    await choosePhoto(user);

    const list = await screen.findByRole("list", { name: "What was read from the photo" });
    // Thumbnail loading may replace its decorative emoji with an image. Assert the
    // read/count semantics, which must stay the same in either loading state.
    const photoRows = within(list).getAllByRole("listitem");
    expect(photoRows).toHaveLength(3);
    expect(photoRows[0]).toHaveTextContent("7 L");
    expect(photoRows[0]).toHaveTextContent("Arla lactose-free milk");
    expect(photoRows[0]).toHaveTextContent("7 packs x 1 L");
    expect(photoRows[0]).toHaveTextContent("high confidence");
    expect(photoRows[1]).toHaveTextContent("Valio Eila 3 % milk");
    expect(photoRows[2]).toHaveTextContent("No product on your stock list matches");
    for (const row of photoRows.slice(1)) {
      expect(row).toHaveTextContent("please count");
      expect(row).toHaveTextContent("low confidence");
      expect(row).not.toHaveTextContent(/\d+ packs x/);
    }
    expect(count("Valio Eila 3 % milk")).toHaveValue("");
    expect(screen.getAllByText(MARK)).toHaveLength(2); // only the Arla row
    expect(screen.getByRole("status")).toHaveTextContent("1 count filled in below; 2 to count by hand.");
  });

  it("keeps the mark on counts from an earlier photo when a second photo is read", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const fixture = await api.readShelfPhoto(PHOTO, "human");
    const answers: ShelfPhotoRead[] = [
      { ...fixture, rows: [fixture.rows[0]] },
      { ...fixture, rows: [fixture.rows[1]] },
    ];
    api.readShelfPhoto = async () => answers.shift() ?? fixture;
    renderApp("/stock", api);
    await choosePhoto(user);
    await waitFor(() => expect(count("Arla lactose-free milk")).toHaveValue("7"));
    expect(screen.getAllByText(MARK)).toHaveLength(2);

    await user.upload(screen.getByLabelText("Choose a photo of the shelf"), PHOTO);
    await waitFor(() => expect(count("Valio Eila 3 % milk")).toHaveValue("6"));
    expect(count("Arla lactose-free milk")).toHaveValue("7");
    expect(screen.getAllByText(MARK)).toHaveLength(4); // both photos' rows, table and phone list

    await user.clear(count("Arla lactose-free milk"));
    await user.type(count("Arla lactose-free milk"), "8");
    expect(screen.getAllByText(MARK)).toHaveLength(2);
  });

  it("stores the counts only when the person presses Save count", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/stock", api);
    await choosePhoto(user);
    await waitFor(() => expect(count("Valio Eila novobox milk")).toHaveValue("20"));

    // The person corrects one number: it is theirs now, so its mark goes.
    await user.clear(count("Valio Eila organic milk"));
    await user.type(count("Valio Eila organic milk"), "5");
    expect(screen.getAllByText(MARK)).toHaveLength(6);
    await user.click(screen.getByRole("button", { name: "Save count" }));

    expect(await screen.findByTestId("stock-count-saved-toast")).toHaveTextContent("Count saved");
    const stock = new Map((await api.getStock()).map((item) => [item.productId, item.onHand]));
    expect([stock.get("462775"), stock.get("463335"), stock.get("462921"), stock.get("463038")]).toEqual([7, 6, 5, 20]);
    await waitFor(() => expect(screen.queryByText(MARK)).not.toBeInTheDocument());
  });

  it("says why a photo was not read and leaves the counts alone", async () => {
    const user = userEvent.setup();
    const api: Api = createMockApi();
    api.readShelfPhoto = async () => {
      throw new ApiError("VISION_NOT_CONFIGURED", "no vision model is configured on this server; count by hand");
    };
    renderApp("/stock", api);
    await choosePhoto(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The photo was not read: no vision model is configured on this server; count by hand",
    );
    expect(count("Arla lactose-free milk")).toHaveValue("");
    expect(screen.queryByText(MARK)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save count" })).toBeDisabled();
  });

  it("reads the sample shelf photo through the same path and saves nothing", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    let reads = 0;
    const read = api.readShelfPhoto;
    api.readShelfPhoto = async (file, actor) => {
      reads += 1;
      expect(file.type).toBe("image/png");
      return read(file, actor);
    };
    let saves = 0;
    api.submitStockCount = async () => {
      saves += 1;
      throw new Error("must not save");
    };
    sampleFetch();
    renderApp("/stock", api);
    await pressSample(user);

    await waitFor(() => expect(count("Arla lactose-free milk")).toHaveValue("7"));
    expect(count("Valio Eila novobox milk")).toHaveValue("20");
    expect(reads).toBe(1);
    expect(screen.getByRole("img", { name: "The photo that was read" })).toBeInTheDocument();
    expect(saves).toBe(0);
  });

  it("shows the photo that was read above the counts", async () => {
    const user = userEvent.setup();
    sampleFetch();
    renderApp("/stock", createMockApi());
    await pressSample(user);

    expect(await screen.findByRole("img", { name: "The photo that was read" })).toBeInTheDocument();
  });

  it("says when the sample photo could not be loaded", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const spy = vi.spyOn(api, "readShelfPhoto");
    sampleFetch(false);
    renderApp("/stock", api);
    await pressSample(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("The sample photo could not be loaded.");
    expect(spy).not.toHaveBeenCalled();
  });

  it("leaves the time out when the gateway sent no timing", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const fixture = await api.readShelfPhoto(PHOTO, "human");
    api.readShelfPhoto = async () => ({ ...fixture, durationMs: null });
    renderApp("/stock", api);
    await user.upload(await screen.findByLabelText("Choose a photo of the shelf"), PHOTO);
    const status = await screen.findByText(/Nemotron 3.5 Super VL read \d+ products\./);
    expect(status).not.toHaveTextContent(/ in .* s\./);
    expect(status).not.toHaveTextContent("0.0 s");
  });
});
