import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { ApiProvider, useApi } from "@/api";
import { LanguageProvider, useLanguage } from "@/lib/i18n";
import { confirmedDemoApproval as approval } from "@/mocks/milk-case";

function ApprovalProbe() {
  const api = useApi();
  const { setLanguage } = useLanguage();
  const [status, setStatus] = useState("loading");
  useEffect(() => {
    void api.listApprovals().then((all) => setStatus(all.find((a) => a.id === approval.id)?.status ?? "missing"));
  }, [api]);
  const approve = async () => {
    const decided = await api.approve(
      {
        approvalId: approval.id,
        approvalRef: approval.approvalRef,
        expectedTotalExVat: approval.totalExVat,
        expectedTotalInclVat: approval.totalInclVat,
      },
      "human",
    );
    setStatus(decided.status);
  };
  return (
    <>
      <output data-testid="status">{status}</output>
      <button onClick={() => void approve()}>Approve</button>
      <button onClick={() => setLanguage("fi")}>FI</button>
    </>
  );
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("ApiProvider", () => {
  it("keeps the mock's data when the language switch remounts the app", async () => {
    const user = userEvent.setup();
    render(
      <LanguageProvider>
        <ApiProvider>
          <ApprovalProbe />
        </ApiProvider>
      </LanguageProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).not.toBe("loading"));
    expect(screen.getByTestId("status").textContent).not.toBe("APPROVED");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("APPROVED"));
    await user.click(screen.getByRole("button", { name: "FI" }));
    expect(document.documentElement.lang).toBe("fi");
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("APPROVED"));
  });
});
