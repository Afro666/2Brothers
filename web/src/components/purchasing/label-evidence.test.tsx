import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { LabelEvidence, type LabelCheck } from "./label-evidence";
const base: LabelCheck = { product_id: "462775", producer: "ARLA OY", label: "GOODS_FROM_FINLAND_BLUE_SWAN",
  label_verified: true, source_url: "https://ruokatieto.fi/yhdistys/jasenyys/", checked_at: "2026-11-14T00:55:00Z",
  scope: "producer", reason: "Exact registered producer" };
it("shows producer-only verification with an official source", () => {
  render(<LabelEvidence check={base} />);
  expect(screen.getByText("Producer registration verified")).toBeVisible();
  expect(screen.getByText(/individual product certification unverified/)).toBeVisible();
  expect(screen.getByRole("link")).toHaveAttribute("href", base.source_url);
});
it("never upgrades unknown or missing evidence into a verified badge", () => {
  const { rerender } = render(<LabelEvidence check={{ ...base, label_verified: "unknown" }} />);
  expect(screen.queryByText("Producer registration verified")).toBeNull();
  rerender(<LabelEvidence check={{ ...base, source_url: null }} />);
  expect(screen.getByText("Verification unknown")).toBeVisible();
  rerender(<LabelEvidence check={{ ...base, label_verified: "not_found", synthetic: true }} />);
  expect(screen.getByText("Producer not found")).toBeVisible();
  expect(screen.getByText(/Synthetic negative control/)).toBeVisible();
});
it("names an unsupported scheme without implying a Hyvää Suomesta check", () => {
  render(<LabelEvidence check={{ ...base, label: "FINNISH_HEART_SYMBOL", label_verified: "unknown", source_url: null }} />);
  expect(screen.getByText(/FINNISH_HEART_SYMBOL · producer scope/)).toBeVisible();
  expect(screen.queryByText(/Hyvää Suomesta/)).toBeNull();
  expect(screen.getByText("Verification unknown")).toBeVisible();
});
