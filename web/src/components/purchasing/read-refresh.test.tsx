import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ReadRefresh } from "@/components/purchasing/read-refresh";
it("labels a burst snapshot and lets the person request fresh results", () => {
  const reload = vi.fn();
  const view = render(<ReadRefresh outdated refreshing={false} reload={reload} />);
  expect(screen.getByRole("status")).toHaveTextContent("last loaded results");
  fireEvent.click(screen.getByRole("button", { name: "Refresh results" })); expect(reload).toHaveBeenCalledOnce();
  view.rerender(<ReadRefresh refreshing={false} reload={reload} />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
