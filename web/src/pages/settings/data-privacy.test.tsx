import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;

afterEach(() => {
  vi.restoreAllMocks();
  if (originalCreateObjectUrl) Object.defineProperty(URL, "createObjectURL", { configurable: true, value: originalCreateObjectUrl });
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevokeObjectUrl) Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: originalRevokeObjectUrl });
  else Reflect.deleteProperty(URL, "revokeObjectURL");
});

function captureDownload() {
  let contents: Blob | null = null;
  const downloads: string[] = [];
  const create = vi.fn((blob: Blob) => {
    contents = blob;
    return "blob:kitchen-export";
  });
  const revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push(this.download);
  });
  return { blob: () => contents, downloads, create, revoke };
}

describe("Data & privacy settings", () => {
  it("loads supplier sharing and an honest retention note", async () => {
    renderApp("/settings/data-privacy");

    expect(await screen.findByRole("checkbox", { name: "Share forecast with Valio Aimo" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Share forecast with Töölö Bakery" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Share forecast with Hakaniemi Fish" })).not.toBeChecked();
    expect(screen.getByText(/Retention period: unknown/)).toBeVisible();
    expect(screen.getByText(/Every change writes an audit entry/)).toBeVisible();
  });

  it.each(["json", "csv"] as const)("downloads a %s file built from orders, proposals and audit", async (format) => {
    const user = userEvent.setup();
    const api = createMockApi();
    const orders = vi.spyOn(api, "listOrders");
    const proposals = vi.spyOn(api, "listApprovals");
    const audit = vi.spyOn(api, "listAudit");
    const download = captureDownload();
    renderApp("/settings/data-privacy", api);

    await user.click(await screen.findByRole("button", { name: format === "json" ? "Download JSON" : "Download CSV" }));
    await waitFor(() => expect(download.create).toHaveBeenCalledOnce());
    const blob = download.blob();
    expect(blob).not.toBeNull();
    const text = await blob!.text();
    if (format === "json") {
      const data = JSON.parse(text);
      expect(data.orders.length).toBeGreaterThan(0);
      expect(data.proposals.length).toBeGreaterThan(0);
      expect(data.audit.length).toBeGreaterThan(0);
    } else {
      expect(text).toContain('"record_type","id","at","status","summary","data"');
      expect(text).toContain('"order"');
      expect(text).toContain('"proposal"');
      expect(text).toContain('"audit"');
    }
    expect(orders).toHaveBeenCalledOnce();
    expect(proposals).toHaveBeenCalled();
    expect(audit).toHaveBeenCalledOnce();
    expect(download.downloads).toEqual([expect.stringMatching(new RegExp(`\\.${format}$`))]);
    expect(download.revoke).toHaveBeenCalledWith("blob:kitchen-export");
  });

  it("saves sharing changes and writes an audit entry", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const share = vi.spyOn(api, "setSharing");
    renderApp("/settings/data-privacy", api);

    await user.click(await screen.findByRole("checkbox", { name: "Share forecast with Töölö Bakery" }));
    await waitFor(() => expect(share).toHaveBeenCalledWith("SUP-BAKERY", true, "human"));
    expect(await screen.findByRole("checkbox", { name: "Share forecast with Töölö Bakery" })).toBeChecked();
    expect((await api.listAudit()).at(-1)).toMatchObject({ kind: "forecast_share", summary: "Forecast sharing turned on for Töölö Bakery" });
  });

  it("requires typed confirmation and only records a deletion request", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const request = vi.spyOn(api, "requestKitchenDeletion");
    const ordersBefore = await api.listOrders();
    renderApp("/settings/data-privacy", api);

    await user.click(await screen.findByRole("button", { name: "Request deletion" }));
    await user.click(screen.getByRole("button", { name: "Record deletion request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Type DELETE to confirm the request.");
    expect(request).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await user.click(screen.getByRole("button", { name: "Record deletion request" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("DELETE", "human"));
    const recorded = await screen.findByText("deletion-request-1");
    expect(recorded).toBeVisible();
    expect(recorded.parentElement).toHaveTextContent("deletion-request-1 was recorded. No data was deleted.");
    expect(await api.listOrders()).toEqual(ordersBefore);
    expect((await api.listAudit()).at(-1)).toMatchObject({ summary: "Kitchen deletion requested", reason: expect.stringContaining("no kitchen data was deleted") });
  });

  it("keeps sharing and deletion read-only for a non-approver while allowing export", async () => {
    const api = createMockApi();
    vi.spyOn(api, "getSession").mockResolvedValue({ name: "Viewer", email: "viewer@demo.kitchen", role: "viewer", canApprove: false });
    renderApp("/settings/data-privacy", api);

    expect(await screen.findByRole("checkbox", { name: "Share forecast with Valio Aimo" })).toBeDisabled();
    expect(screen.getByText("Only an approver can change forecast sharing.")).toBeVisible();
    expect(screen.getByText("Only an approver can request kitchen deletion.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Request deletion" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeEnabled();
  });
});
