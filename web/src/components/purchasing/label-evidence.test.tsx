import { render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { gatewayRequest } from "@/api/http";
import { formatDateTime } from "@/lib/format";
import { LabelEvidence, LabelVerificationDemo, type LabelCheck } from "./label-evidence";

vi.mock("@/api/http", () => ({ gatewayRequest: vi.fn() }));

const base: LabelCheck = { product_id: "462775", producer: "ARLA OY", label: "GOODS_FROM_FINLAND_BLUE_SWAN",
  label_verified: true, source_url: "https://ruokatieto.fi/yhdistys/jasenyys/", checked_at: "2026-11-14T00:55:00Z",
  scope: "producer", reason: "Exact registered producer" };

beforeEach(() => vi.mocked(gatewayRequest).mockReset());

it("shows producer-only verification with an official source", () => {
  render(<LabelEvidence check={base} />);
  expect(screen.getByText("Producer registration verified")).toBeVisible();
  expect(screen.getByText(/individual product certification unverified/)).toBeVisible();
  expect(screen.getByText(`Exact registered producer · checked ${formatDateTime(base.checked_at)}`)).toBeVisible();
  expect(screen.queryByText(/2026-11-14T00:55:00Z/)).toBeNull();
  expect(screen.getByRole("link")).toHaveAttribute("href", base.source_url);
});
it("never upgrades unknown or missing evidence into a verified badge", () => {
  const { rerender } = render(<LabelEvidence check={{ ...base, label_verified: "unknown" }} />);
  expect(screen.queryByText("Producer registration verified")).toBeNull();
  rerender(<LabelEvidence check={{ ...base, checked_at: null }} />);
  expect(screen.getByText("Exact registered producer · not checked")).toBeVisible();
  expect(screen.queryByText(/checked unknown/)).toBeNull();
  rerender(<LabelEvidence check={{ ...base, source_url: null }} />);
  expect(screen.getByText("Verification unknown")).toBeVisible();
  rerender(<LabelEvidence check={{ ...base, label_verified: "not_found", synthetic: true }} />);
  expect(screen.getByText("Producer not found")).toBeVisible();
  expect(screen.getByText(/Synthetic negative control/)).toBeVisible();
  expect(screen.getByText(/Test row/)).toBeVisible();
});
it("names an unsupported scheme without implying a Hyvää Suomesta check", () => {
  render(<LabelEvidence check={{ ...base, label: "FINNISH_HEART_SYMBOL", label_verified: "unknown", source_url: null }} />);
  expect(screen.getByText(/Heart Symbol · producer scope/)).toBeVisible();
  expect(screen.queryByText(/FINNISH_HEART_SYMBOL/)).toBeNull();
  expect(screen.queryByText(/Hyvää Suomesta/)).toBeNull();
  expect(screen.getByText("Verification unknown")).toBeVisible();
});

it("puts unsupported registers in one collapsed group below the checked rows", async () => {
  const unsupported: LabelCheck = {
    ...base,
    product_id: "462535",
    label: "FINNISH_HEART_SYMBOL",
    label_verified: "unknown",
    source_url: null,
    checked_at: null,
    reason: "Unsupported label register",
  };
  vi.mocked(gatewayRequest).mockResolvedValue({
    checks: [base, unsupported],
    negative_control: { ...base, label_verified: "not_found", synthetic: true },
  });
  render(<LabelVerificationDemo />);

  const summary = await screen.findByText("Not checked: 1 labels with no public register");
  const group = summary.closest("details");
  expect(group).not.toBeNull();
  expect(group).not.toHaveAttribute("open");
  expect(within(group as HTMLElement).getByText(/Heart Symbol/)).toBeInTheDocument();
  expect(within(group as HTMLElement).getByText(/not checked/)).toBeInTheDocument();
  const verified = screen.getByText("Producer registration verified");
  expect(verified.compareDocumentPosition(group as HTMLElement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText(/Test row/)).toBeVisible();
});
