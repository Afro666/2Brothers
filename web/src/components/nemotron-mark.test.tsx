import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import nvidiaLogo from "@/assets/nvidia-logo.svg";
import { isNemotron, NemotronMark } from "@/components/nemotron-mark";

describe("NemotronMark", () => {
  it("shows NVIDIA's logo as decoration: empty alt, hidden from screen readers", () => {
    const { container } = render(<p>Written by Nemotron 3.5 Super VL<NemotronMark side="after" /></p>);
    const mark = screen.getByTestId("nemotron-mark");
    expect(mark).toHaveAttribute("aria-hidden", "true");
    const img = mark.querySelector("img")!;
    expect(img).toHaveAttribute("alt", "");
    expect(img.getAttribute("src")).toBe(nvidiaLogo);
    // The words stay as they are; the logo adds no text.
    expect(container.querySelector("p")).toHaveTextContent(/^Written by Nemotron 3\.5 Super VL$/);
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("shows nothing when no model ran (the parser or a rule answered)", () => {
    render(<p>Proposed by the gateway’s request parser<NemotronMark when={false} /></p>);
    expect(screen.queryByTestId("nemotron-mark")).toBeNull();
  });

  it("knows Nemotron by its id and by its name, and nothing else", () => {
    expect(isNemotron("nemotron-3.5-super-vl")).toBe(true);
    expect(isNemotron("Nemotron 3.5 Super VL")).toBe(true);
    expect(isNemotron("rule")).toBe(false);
    expect(isNemotron("parser")).toBe(false);
    expect(isNemotron("")).toBe(false);
    expect(isNemotron(undefined)).toBe(false);
  });
});
