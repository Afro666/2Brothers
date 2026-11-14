import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mapLabelPhoto } from "@/api/http-label-photo";
import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { LABEL_ANSWER } from "@/test/label-photo-fixture";
import { renderApp } from "@/test/render";

vi.mock("@/lib/shelf-photo", async (original) => ({ ...await original<typeof import("@/lib/shelf-photo")>(), downscalePhoto: vi.fn(async (file: Blob) => file) }));

const PRODUCT = "Arla 1 L lactose free fat free UHT milk drink";
const answer = (patch: Record<string, unknown> = {}) => mapLabelPhoto({ ...LABEL_ANSWER, ...patch }, "ORD-1042", "462775");
const photo = () => new File(["photo"], "label.jpg", { type: "image/jpeg" });

async function upload(api = createMockApi()) {
  const user = userEvent.setup();
  renderApp("/orders/ORD-1042", api);
  const input = await screen.findByLabelText(`Choose a label photo for ${PRODUCT}`, { selector: "input" });
  expect(input).toHaveAttribute("accept", "image/*");
  expect(input).toHaveAttribute("capture", "environment");
  expect(screen.getByRole("button", { name: `Photo of the label: ${PRODUCT}` })).toBeEnabled();
  await user.upload(input, photo());
  return within(await screen.findByTestId("label-photo-result", {}, { timeout: 5000 }));
}

describe("Photo of the label on a placed order (#1175)", () => {
  it("warns when the label lists an allergen the kitchen excludes, and saves nothing", async () => {
    const api = createMockApi();
    const read = vi.spyOn(api, "readLabelPhoto").mockResolvedValue(answer());
    const save = vi.spyOn(api, "submitStockCount");
    const result = await upload(api);
    expect(result.getByRole("alert")).toHaveTextContent("The label lists Peanuts, which this kitchen excludes. Do not use it: a person must check.");
    expect(result.getByText(/“MAITO” \(Milk\)/)).toBeVisible();
    expect(result.getByText(/“maapähkinää” \(Peanuts\)/)).toBeVisible();
    expect(result.getByText(/Read by Nemotron 3.5 Super VL in 3.1 s\./)).toHaveTextContent("It does not change the catalog, the order or the stock.");
    expect(read).toHaveBeenCalledWith("ORD-1042", "462775", expect.any(Blob), "human");
    expect(save).not.toHaveBeenCalled();
  });

  it("says a match in the agreed words, with no green", async () => {
    const api = createMockApi();
    vi.spyOn(api, "readLabelPhoto").mockResolvedValue(answer({ outcome: "AGREES", excluded_hits: [], differences: [], duration_ms: undefined }));
    const result = await upload(api);
    const line = result.getByText("The label we read agrees with the catalog. Read the label yourself before use.");
    expect(line).toHaveAttribute("role", "status");
    expect(line.className).not.toMatch(/green|success/);
    expect(result.getByText(/Read by Nemotron 3.5 Super VL\./)).toBeVisible();
  });

  it("asks a person to check when no allergen statement was read", async () => {
    const api = createMockApi();
    vi.spyOn(api, "readLabelPhoto").mockResolvedValue(answer({
      outcome: "PLEASE_CHECK", excluded_hits: [], differences: [], please_check: ["NO_STATEMENT_READ", "WORD_UNKNOWN"],
      label: { ...LABEL_ANSWER.label, contains: [], may_contain: [], unknown_words: ["kaneli"] },
    }));
    const result = await upload(api);
    expect(result.getByRole("status")).toHaveTextContent("Please check: we could not read an allergen statement. That does not mean there are no allergens.");
    expect(result.getByText("Please check: some words on the label are not in our allergen table. Read the label yourself.")).toBeVisible();
    expect(result.getByText(/“kaneli”/)).toBeVisible();
    expect(result.getAllByText("nothing read")).toHaveLength(2);
  });

  it("shows the label as read when the catalog has no allergen data", async () => {
    const api = createMockApi();
    vi.spyOn(api, "readLabelPhoto").mockResolvedValue(answer({ outcome: "CATALOG_UNKNOWN", excluded_hits: [], differences: [], catalog_allergen_data: "UNKNOWN" }));
    const result = await upload(api);
    expect(result.getByRole("status")).toHaveTextContent("The catalog has no allergen data for this product. The label says: Milk, Peanuts. Read the label yourself before use.");
  });

  it("says busy and model errors in plain words", async () => {
    const api = createMockApi();
    const read = vi.spyOn(api, "readLabelPhoto").mockRejectedValueOnce(new ApiError("RATE_LIMITED", "Too many requests - wait a minute and try again."));
    const user = userEvent.setup();
    renderApp("/orders/ORD-1042", api);
    const input = await screen.findByLabelText(`Choose a label photo for ${PRODUCT}`, { selector: "input" });
    await user.upload(input, photo());
    expect(await screen.findByRole("alert")).toHaveTextContent("Another label is being read. Wait for it, then try again.");
    read.mockRejectedValueOnce(new ApiError("VISION_TIMEOUT", "The label could not be read; read it yourself", {}, 504));
    await user.upload(input, photo());
    expect(await screen.findByText("The model is not answering right now. Read the label yourself, or try again later.")).toBeVisible();
    expect(screen.queryByTestId("label-photo-result")).not.toBeInTheDocument();
  });

  it("works in mock mode with the prepared peanut sample", async () => {
    const result = await upload();
    expect(result.getByRole("alert")).toHaveTextContent("Peanuts");
  });
});
