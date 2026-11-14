import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import type { Api, ProposalExplanation } from "@/api/types";
import { LanguageProvider, useLanguage } from "@/lib/i18n";
import {
  EXPLANATION_POLL_LIMIT,
  EXPLANATION_POLL_MS,
  EXPLANATION_POLL_WINDOW_MS,
  useProposalExplanation,
} from "@/lib/proposal-explanation";

const text: ProposalExplanation = {
  text: "You chose 950 L of Valio Eila 3 % milk.",
  model: "nemotron-3.5-super-vl",
  durationMs: 1540,
};

/** The mock, with its explanation answered by `answers` and every call counted. */
function apiWith(answers: (ProposalExplanation | null)[] | (() => Promise<ProposalExplanation | null>)) {
  const api = createMockApi();
  const list = typeof answers === "function" ? null : [...answers];
  const ask = typeof answers === "function" ? answers : () => Promise.resolve(list!.shift() ?? null);
  api.getProposalExplanation = vi.fn(ask);
  return api;
}

function Harness({ api, proposalId = "APR-311", enabled = true, source = 1947.5 }: {
  api: Api;
  proposalId?: string;
  enabled?: boolean;
  source?: unknown;
}) {
  const explanation = useProposalExplanation(api, proposalId, enabled, source);
  return <p data-testid="text">{explanation?.text ?? "none"}</p>;
}

function renderHarness(props: Parameters<typeof Harness>[0]) {
  return render(
    <LanguageProvider>
      <Harness {...props} />
    </LanguageProvider>,
  );
}

describe("useProposalExplanation (#1173)", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows nothing while there is no explanation", async () => {
    const api = apiWith([null]);
    renderHarness({ api });
    await act(async () => {});
    expect(screen.getByTestId("text")).toHaveTextContent("none");
    expect(api.getProposalExplanation).toHaveBeenCalledWith("APR-311", "en");
  });

  it("asks again every 3 s and shows the text that arrives on the second poll", async () => {
    const api = apiWith([null, text]);
    renderHarness({ api });
    await act(async () => {});
    expect(screen.getByTestId("text")).toHaveTextContent("none");
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_MS);
    });
    expect(screen.getByTestId("text")).toHaveTextContent(text.text);
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_MS * 10);
    });
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(2);
  });

  it("backs off 3 s, 5 s, 10 s, then 15 s and shows a text that arrives after the 30 s throttle", async () => {
    // Asks at 0, 3, 8, 18, 33 s: the fifth answer, after the server's 30 s throttle, has the text.
    const api = apiWith([null, null, null, null, text]);
    renderHarness({ api });
    await act(async () => {});
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(1);
    for (const [wait, calls] of [[3000, 2], [5000, 3], [10000, 4]] as const) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(wait - 1);
      });
      expect(api.getProposalExplanation).toHaveBeenCalledTimes(calls - 1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(api.getProposalExplanation).toHaveBeenCalledTimes(calls);
    }
    expect(screen.getByTestId("text")).toHaveTextContent("none");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(5);
    expect(screen.getByTestId("text")).toHaveTextContent(text.text);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_WINDOW_MS);
    });
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(5);
  });

  it("stops after about two minutes of empty answers", async () => {
    const api = apiWith([null]);
    renderHarness({ api });
    await act(async () => {});
    expect(EXPLANATION_POLL_WINDOW_MS).toBeGreaterThanOrEqual(110_000);
    expect(EXPLANATION_POLL_WINDOW_MS).toBeLessThanOrEqual(130_000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_WINDOW_MS);
    });
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(EXPLANATION_POLL_LIMIT);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_WINDOW_MS);
    });
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(EXPLANATION_POLL_LIMIT);
  });

  it("stops on unmount", async () => {
    const api = apiWith([null]);
    const { unmount } = renderHarness({ api });
    await act(async () => {});
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_WINDOW_MS * 2);
    });
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(1);
  });

  it("does not ask for a proposal that is not waiting for a decision", async () => {
    const api = apiWith([text]);
    renderHarness({ api, enabled: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_MS * 3);
    });
    expect(api.getProposalExplanation).not.toHaveBeenCalled();
    expect(screen.getByTestId("text")).toHaveTextContent("none");
  });

  it("asks again when the offer changes and drops the old text meanwhile", async () => {
    const api = apiWith(async () => text);
    const { rerender } = renderHarness({ api });
    await act(async () => {});
    expect(screen.getByTestId("text")).toHaveTextContent(text.text);
    rerender(
      <LanguageProvider>
        <Harness api={api} source={2075} />
      </LanguageProvider>,
    );
    expect(screen.getByTestId("text")).toHaveTextContent("none");
    await act(async () => {});
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("text")).toHaveTextContent(text.text);
  });

  it("asks in Finnish after the language changes", async () => {
    const api = apiWith([text, { ...text, text: "Valitsit 950 L Valio Eila 3 % -maitoa." }]);
    let setLanguage: ((language: "en" | "fi") => void) | null = null;
    function Probe() {
      const { setLanguage: set } = useLanguage();
      setLanguage = set;
      return <Harness api={api} />;
    }
    render(
      <LanguageProvider>
        <Probe />
      </LanguageProvider>,
    );
    await act(async () => {});
    expect(api.getProposalExplanation).toHaveBeenLastCalledWith("APR-311", "en");
    act(() => setLanguage?.("fi"));
    await act(async () => {});
    expect(api.getProposalExplanation).toHaveBeenLastCalledWith("APR-311", "fi");
    expect(screen.getByTestId("text")).toHaveTextContent("Valitsit 950 L Valio Eila 3 % -maitoa.");
  });
});
