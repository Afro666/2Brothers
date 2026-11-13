import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("SuppliersPage", () => {
  beforeEach(() => localStorage.clear());

  it("shows the three suppliers and marks missing terms as not set", async () => {
    renderApp("/suppliers", createMockApi());

    const valio = (await screen.findByText("Valio Aimo")).closest("[data-slot=card]");
    expect(valio).not.toBeNull();
    const valioCard = within(valio as HTMLElement);
    expect(valioCard.getByText("Live API")).toBeInTheDocument();
    expect(valioCard.getByText("€250.00")).toBeInTheDocument();
    expect(valioCard.getByText("€29.00")).toBeInTheDocument();
    expect(valioCard.getByText("Mon, Tue, Wed, Thu, Fri")).toBeInTheDocument();
    expect(valioCard.getByText("17:00")).toBeInTheDocument();
    expect(valioCard.getByText("1 day")).toBeInTheDocument();

    expect(await screen.findByRole("checkbox", { name: "Share our forecast with Valio Aimo" })).toBeEnabled();
    expect(await screen.findByRole("heading", { name: "Töölö Bakery" })).toBeInTheDocument();
    expect(screen.getByText("Manual entry")).toBeInTheDocument();

    const fish = screen.getByRole("heading", { name: "Hakaniemi Fish" }).closest("[data-slot=card]");
    const fishCard = within(fish as HTMLElement);
    expect(fishCard.getByText("CSV price list")).toBeInTheDocument();
    expect(fishCard.getAllByText("not set")).toHaveLength(5);
  });

  it("adds a supplier with only a name and leaves the terms unset", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/suppliers", api);

    await user.click(await screen.findByRole("button", { name: "Add supplier" }));
    const dialog = await screen.findByRole("dialog", { name: "Add supplier" });
    await user.type(within(dialog).getByLabelText("Name"), "Kallio Greens");
    await user.click(within(dialog).getByRole("button", { name: "Save supplier" }));

    expect(await screen.findByRole("heading", { name: "Kallio Greens" })).toBeInTheDocument();
    const saved = (await api.listSuppliers()).find((supplier) => supplier.name === "Kallio Greens");
    expect(saved).toMatchObject({
      freeDeliveryThresholdEur: null,
      deliveryFeeEur: null,
      orderDays: null,
      cutoffTime: null,
      leadTimeDays: null,
    });
  });

  it("shows the API's error for a blank name in the dialog", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/suppliers", api);

    await user.click(await screen.findByRole("button", { name: "Add supplier" }));
    const dialog = await screen.findByRole("dialog", { name: "Add supplier" });
    await user.click(within(dialog).getByRole("button", { name: "Save supplier" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Name must not be blank.");
    expect(screen.getByRole("dialog", { name: "Add supplier" })).toBeInTheDocument();
  });

  it("edits a term and shows the new value on the card", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/suppliers", api);

    const fishCard = (await screen.findByRole("heading", { name: "Hakaniemi Fish" })).closest("[data-slot=card]");
    await user.click(within(fishCard as HTMLElement).getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Hakaniemi Fish" });
    await user.clear(within(dialog).getByLabelText("Lead time (days)"));
    await user.type(within(dialog).getByLabelText("Lead time (days)"), "2");
    await user.click(within(dialog).getByRole("button", { name: "Save supplier" }));

    expect((await api.listSuppliers()).find((supplier) => supplier.id === "SUP-FISH")?.leadTimeDays).toBe(2);
    await waitFor(() => {
      const updatedCard = screen.getByRole("heading", { name: "Hakaniemi Fish" }).closest("[data-slot=card]");
      expect(within(updatedCard as HTMLElement).getByText("2 days")).toBeInTheDocument();
    });
  });

  it("keeps an invalid term in the field and blocks saving", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/suppliers", api);
    const fishCard = (await screen.findByRole("heading", { name: "Hakaniemi Fish" })).closest("[data-slot=card]");
    await user.click(within(fishCard as HTMLElement).getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Hakaniemi Fish" });
    const leadTime = within(dialog).getByLabelText("Lead time (days)");
    await user.clear(leadTime);
    await user.type(leadTime, "-2");
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Value cannot be negative.");
    await user.click(within(dialog).getByRole("button", { name: "Save supplier" }));
    expect(leadTime).toHaveValue("-2");
    expect((await api.listSuppliers()).find((supplier) => supplier.id === "SUP-FISH")?.leadTimeDays).toBeNull();
  });

  it("opens an empty add form after cancelling an edit", async () => {
    const user = userEvent.setup();
    renderApp("/suppliers", createMockApi());
    const fishCard = (await screen.findByRole("heading", { name: "Hakaniemi Fish" })).closest("[data-slot=card]");
    await user.click(within(fishCard as HTMLElement).getByRole("button", { name: "Edit" }));
    let dialog = await screen.findByRole("dialog", { name: "Edit Hakaniemi Fish" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(await screen.findByRole("button", { name: "Add supplier" }));
    dialog = await screen.findByRole("dialog", { name: "Add supplier" });
    expect(within(dialog).getByLabelText("Name")).toHaveValue("");
  });

  it("keeps the bakery and shows the IN_USE message when deleting", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/suppliers", api);

    const bakery = (await screen.findByRole("heading", { name: "Töölö Bakery" })).closest("[data-slot=card]");
    await user.click(within(bakery as HTMLElement).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete Töölö Bakery?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete supplier" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Töölö Bakery still supplies some of your own products. Move or delete those first.",
    );
    expect(screen.getByRole("heading", { name: "Töölö Bakery" })).toBeInTheDocument();
    expect((await api.listSuppliers()).some((supplier) => supplier.id === "SUP-BAKERY")).toBe(true);
  });

  it("deletes a supplier that is not in use", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/suppliers", api);

    const valio = (await screen.findByText("Valio Aimo")).closest("[data-slot=card]");
    await user.click(within(valio as HTMLElement).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete Valio Aimo?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete supplier" }));

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Valio Aimo" })).not.toBeInTheDocument());
  });

  it("turning Valio's forecast sharing off records a forecast_share audit event", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/suppliers", api);

    const checkbox = await screen.findByRole("checkbox", { name: "Share our forecast with Valio Aimo" });
    await waitFor(() => expect(checkbox).toBeEnabled());
    expect(checkbox).toBeChecked();
    await user.click(checkbox);

    await waitFor(() => expect(checkbox).not.toBeChecked());
    const events = await api.listAudit();
    expect(events.filter((event) => event.kind === "forecast_share").at(-1)).toMatchObject({
      actor: "human",
      summary: "Forecast sharing turned off for Valio Aimo",
    });
  });
});
