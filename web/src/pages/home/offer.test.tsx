import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { sampleSupplierOffer } from "@/api/mock-offers";
import { ApiError } from "@/api/types";
import { madeByLabel } from "@/pages/home/offer";
import { renderApp } from "@/test/render";

const title = () => screen.findByText("Offer from Valio Aimo");

describe("SupplierOfferTile", () => {
  beforeEach(() => localStorage.clear());

  it("shows the open offer: the product, what it replaces, the quantity, the reason and who wrote it", async () => {
    renderApp("/", createMockApi());

    expect(await title()).toBeInTheDocument();
    expect(screen.getByText("Valio Eila lactose-free milk drink 1 L")).toBeInTheDocument();
    expect(
      screen.getByText(/in place of Arla lactose-free milk 1 L, which is predicted short on/),
    ).toBeInTheDocument();
    expect(screen.getByText(/42 L, from your own forecast/)).toBeInTheDocument();
    expect(screen.getByText(sampleSupplierOffer.reason)).toBeInTheDocument();
    expect(screen.getByText(/written by Valio's selling agent \(\s*Nemotron 3.5 Super VL\)/)).toBeInTheDocument();
    expect(screen.getByText(/This is a suggestion, not an order/)).toBeInTheDocument();
    expect(screen.queryByText(/no allergen data/)).toBeNull();
  });

  it("asks for a label check when the catalog has no allergen data for the product", async () => {
    const api = createMockApi();
    api.listSupplierOffers = async () => [{ ...sampleSupplierOffer, allergenDataKnown: false }];
    renderApp("/", api);

    expect(
      await screen.findByText("The catalog has no allergen data for this product. Check the label before you approve."),
    ).toBeInTheDocument();
  });

  it("shows the supplier's text as text, never as markup", async () => {
    const api = createMockApi();
    api.listSupplierOffers = async () => [{ ...sampleSupplierOffer, reason: '<img src=x onerror="alert(1)"><b>Buy</b>' }];
    renderApp("/", api);

    expect(await screen.findByText('<img src=x onerror="alert(1)"><b>Buy</b>')).toBeInTheDocument();
    expect(document.querySelector("blockquote img, blockquote b")).toBeNull();
  });

  it("accepts the offer once and goes to the inbox", async () => {
    const api = createMockApi();
    const accept = vi.spyOn(api, "acceptSupplierOffer");
    const { router } = renderApp("/", api);

    await userEvent.click(await screen.findByRole("button", { name: "Make a proposal" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/approvals"));
    expect(accept).toHaveBeenCalledTimes(1);
    expect(accept).toHaveBeenCalledWith("OFFER-DEMO-1", "human");
  });

  it("stays on Home and says so when the proposal came back rejected", async () => {
    const api = createMockApi();
    api.acceptSupplierOffer = async () => ({
      offer: sampleSupplierOffer,
      proposalId: "p-1",
      proposalStatus: "REJECTED",
    });
    const { router } = renderApp("/", api);

    await userEvent.click(await screen.findByRole("button", { name: "Make a proposal" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /Valio Aimo cannot deliver Valio Eila lactose-free milk drink 1 L for .* No proposal was made\./,
    );
    expect(router.state.location.pathname).toBe("/");
    expect(screen.getByRole("button", { name: "No thanks" })).toBeEnabled();
  });

  it("hides the tile after No thanks", async () => {
    const api = createMockApi();
    const decline = vi.spyOn(api, "declineSupplierOffer");
    renderApp("/", api);

    await userEvent.click(await screen.findByRole("button", { name: "No thanks" }));

    await waitFor(() => expect(screen.queryByText("Offer from Valio Aimo")).not.toBeInTheDocument());
    expect(decline).toHaveBeenCalledWith("OFFER-DEMO-1", "human");
    expect((await api.listSupplierOffers())[0].status).toBe("DECLINED");
  });

  it("shows the gateway's refusal and keeps the offer", async () => {
    const api = createMockApi();
    api.acceptSupplierOffer = async () => {
      throw new ApiError("SHARING_REQUIRED", "The kitchen no longer shares its forecast with this supplier.", {}, 403);
    };
    renderApp("/", api);

    await userEvent.click(await screen.findByRole("button", { name: "Make a proposal" }));

    expect(await screen.findByRole("status")).toHaveTextContent("no longer shares its forecast");
    expect(screen.getByRole("button", { name: "Make a proposal" })).toBeEnabled();
  });

  it.each([
    ["no offer", []],
    ["only decided or expired offers", [{ ...sampleSupplierOffer, status: "EXPIRED" as const }]],
  ])("shows no tile with %s", async (_, offers) => {
    const api = createMockApi();
    api.listSupplierOffers = async () => offers;
    renderApp("/", api);

    expect(await screen.findByText("Waiting for your approval")).toBeInTheDocument();
    expect(screen.queryByText(/Offer from/)).not.toBeInTheDocument();
  });

  it("shows no tile, and the rest of Home, when the offers cannot be read", async () => {
    const api = createMockApi();
    api.listSupplierOffers = async () => {
      throw new ApiError("NOT_FOUND", "Not found", {}, 404);
    };
    renderApp("/", api);

    expect(await screen.findByText("Waiting for your approval")).toBeInTheDocument();
    expect(screen.queryByText(/Offer from/)).not.toBeInTheDocument();
  });

  it("disables both buttons for an account that cannot approve", async () => {
    const api = createMockApi();
    const session = await api.getSession();
    api.getSession = async () => ({ ...session!, role: "viewer", canApprove: false });
    renderApp("/", api);

    expect(await screen.findByRole("button", { name: "Make a proposal" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "No thanks" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Your account cannot accept or decline offers.");
  });

  it("is not on the Valio planner's Home", async () => {
    localStorage.setItem("purchasing-role", "valio_planner");
    const api = createMockApi();
    await api.signIn("planner@demo.valio", "demo-kitchen-2026");
    renderApp("/", api);

    expect(await screen.findByText("Where demand may outrun supply.")).toBeInTheDocument();
    expect(screen.queryByText(/Offer from/)).not.toBeInTheDocument();
  });
});

describe("madeByLabel", () => {
  it("names the model, the rule, or what the supplier sent", () => {
    expect(madeByLabel("nemotron-3.5-super-vl")).toBe("Nemotron 3.5 Super VL");
    expect(madeByLabel("rule")).toBe("picked by rule, not by a model");
    expect(madeByLabel("Sanna, Valio sales")).toBe("Sanna, Valio sales");
    expect(madeByLabel("")).toBe("unknown");
  });
});
