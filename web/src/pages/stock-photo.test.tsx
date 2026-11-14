import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

describe("StockPage: count from a photo", () => {
  beforeEach(() => localStorage.clear());

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
    expect(within(list).getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      "7 LArla lactose-free milk7 packs x 1 L. Read on the pack: “Arla lactose free 1L” (high confidence)",
      "please countValio Eila 3 % milkRead on the pack: “Valio Eila 3% 1L” (low confidence)",
      "please countNo product on your stock list matchesRead on the pack: “Arla L m” (low confidence)",
    ]);
    expect(count("Valio Eila 3 % milk")).toHaveValue("");
    expect(screen.getAllByText(MARK)).toHaveLength(2); // only the Arla row
    expect(screen.getByRole("status")).toHaveTextContent("1 count filled in below; 2 to count by hand.");
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
});
