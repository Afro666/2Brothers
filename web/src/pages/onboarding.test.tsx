import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { domainOf, lookupKitchenBrandMock } from "@/api/mock-onboarding";
import { ApiError, type Api } from "@/api/types";
import { safeLogoUrl } from "@/lib/kitchen-brand";
import { renderApp } from "@/test/render";

const FROM_CONTEXT = /From your website via Context\.dev/;

function field(name: string): HTMLElement {
  const element = document.querySelector<HTMLElement>(`[data-field="${name}"]`);
  if (!element) throw new Error(`No field ${name}`);
  return element;
}

async function lookUp(query: string, api?: Api) {
  const user = userEvent.setup();
  renderApp("/onboarding", api);
  await user.type(await screen.findByLabelText("Work email or website"), query);
  await user.click(screen.getByRole("button", { name: "Look up" }));
  return user;
}

describe("domainOf", () => {
  it("takes the domain from an email or a website", () => {
    expect(domainOf({ email: " Chef@HotelKuusi.fi " })).toBe("hotelkuusi.fi");
    expect(domainOf({ website: "https://www.hotelkuusi.fi/en/rooms?x=1" })).toBe("hotelkuusi.fi");
    expect(domainOf({ website: "hotelkuusi.fi" })).toBe("hotelkuusi.fi");
    expect(domainOf({ email: "no-at-sign" })).toBeNull();
    expect(domainOf({ website: "not a site" })).toBeNull();
  });

  it("gives every unknown field a null value and a null source", async () => {
    const lookup = await lookupKitchenBrandMock({ website: "lumikoulu.fi" });
    expect(lookup.logoUrl).toEqual({ value: null, source: null });
    expect(lookup.openingHours).toEqual({ value: null, source: null });
    expect(lookup.kitchenType.source?.endpoint).toBe("POST /v1/brand/retrieve");
  });
});

describe("safeLogoUrl", () => {
  it("keeps only https: and data:image/ logo URLs", () => {
    expect(safeLogoUrl("https://cdn.example/logo.png")).toBe("https://cdn.example/logo.png");
    expect(safeLogoUrl("data:image/png;base64,AAAA")).toBe("data:image/png;base64,AAAA");
    expect(safeLogoUrl("http://cdn.example/logo.png")).toBeNull();
    expect(safeLogoUrl("javascript:alert(1)")).toBeNull();
    expect(safeLogoUrl("data:text/html,<b>x</b>")).toBeNull();
    expect(safeLogoUrl("")).toBeNull();
    expect(safeLogoUrl(null)).toBeNull();
  });
});

describe("OnboardingPage", () => {
  beforeEach(() => localStorage.clear());

  it("names the Context.dev endpoint and saves nothing before a lookup", async () => {
    renderApp("/onboarding");
    expect(await screen.findByRole("heading", { level: 1, name: "Set up your kitchen" })).toBeVisible();
    expect(screen.getByText(/Powered by Context\.dev/)).toHaveTextContent("POST /v1/brand/retrieve");
    expect(screen.queryByRole("form", { name: "Kitchen profile" })).not.toBeInTheDocument();
    expect(localStorage.getItem("kitchen-brand")).toBeNull();
  });

  it("fills the form from a website and marks each field with its source", async () => {
    await lookUp("https://www.hotelkuusi.fi");

    expect(await screen.findByLabelText("Kitchen name")).toHaveValue("Hotel Kuusi");
    expect(screen.getByLabelText("Street")).toHaveValue("Satakunnankatu 41");
    expect(screen.getByLabelText("Postal code")).toHaveValue("33210");
    expect(screen.getByLabelText("City")).toHaveValue("Tampere");
    expect(screen.getByLabelText("Brand colours")).toHaveValue("#1f4d3a, #e9d8a6, #c8553d");
    expect(screen.getByRole("combobox", { name: "Kitchen type" })).toHaveTextContent("Hotel");
    expect(within(field("logoUrl")).getByRole("img", { name: "Hotel Kuusi logo" })).toBeVisible();
    for (const name of ["name", "logoUrl", "colors", "street", "city", "kitchenType"]) {
      expect(within(field(name)).getByText(FROM_CONTEXT)).toHaveTextContent("POST /v1/brand/retrieve");
    }
    expect(within(field("openingHours")).getByText(FROM_CONTEXT)).toHaveTextContent("POST /v1/web/scrape");
    expect(screen.getByLabelText("Kitchen name")).toHaveAccessibleDescription(/From your website via Context\.dev/);
    // Nothing is stored until the person confirms.
    expect(localStorage.getItem("kitchen-brand")).toBeNull();
  });

  it("marks an edited field, saves on confirm and shows the logo in the app shell", async () => {
    const user = await lookUp("chef@hotelkuusi.fi");
    const name = await screen.findByLabelText("Kitchen name");
    await user.clear(name);
    await user.type(name, "Hotel Kuusi Kitchen");
    expect(within(field("name")).getByText("Edited by you")).toBeVisible();
    expect(within(field("city")).getByText(FROM_CONTEXT)).toBeVisible();

    await user.click(screen.getByRole("combobox", { name: "Kitchen type" }));
    await user.click(await screen.findByRole("option", { name: "Restaurant" }));
    expect(within(field("kitchenType")).getByText("Edited by you")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Confirm and save" }));

    const saved = await screen.findByLabelText("Saved kitchen profile");
    expect(saved).toHaveTextContent("Hotel Kuusi Kitchen");
    expect(saved).toHaveTextContent("Restaurant");
    expect(saved).toHaveTextContent("Satakunnankatu 41, 33210 Tampere, Finland");
    const stored = JSON.parse(localStorage.getItem("kitchen-brand") ?? "null");
    expect(stored).toMatchObject({ domain: "hotelkuusi.fi", name: "Hotel Kuusi Kitchen", kitchenType: "restaurant" });
    expect(stored.colors).toEqual(["#1f4d3a", "#e9d8a6", "#c8553d"]);
    // The shell's brand (sidebar and phone top bar) now carries the logo.
    expect(screen.getAllByRole("img", { name: "Hotel Kuusi Kitchen logo" }).length).toBeGreaterThan(0);
  });

  it("leaves what the provider does not know empty and marked unknown", async () => {
    await lookUp("keittio@lumikoulu.fi");

    expect(await screen.findByLabelText("Kitchen name")).toHaveValue("Lumi School");
    expect(screen.getByRole("combobox", { name: "Kitchen type" })).toHaveTextContent("School");
    expect(screen.getByLabelText("City")).toHaveValue("Oulu");
    for (const name of ["street", "postalCode", "colors", "openingHours"]) {
      expect(within(field(name)).getByRole("textbox")).toHaveValue("");
      expect(within(field(name)).getByText(/^Unknown: not found on your website/)).toBeVisible();
    }
    expect(within(field("logoUrl")).queryByRole("img")).not.toBeInTheDocument();
    expect(within(field("logoUrl")).getByText(/^Unknown/)).toBeVisible();
  });

  it("asks for the website when the email is a personal one", async () => {
    await lookUp("kuusi.chef@gmail.com");
    expect(await screen.findByRole("status")).toHaveTextContent("Type the kitchen's website instead.");
    expect(screen.getByLabelText("Kitchen name")).toHaveValue("");
  });

  it("says when Context.dev found nothing and leaves every field unknown", async () => {
    await lookUp("example-kitchen.fi");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Context.dev found nothing for example-kitchen.fi. Fill in the form yourself.",
    );
    expect(screen.getByLabelText("Kitchen name")).toHaveValue("");
    expect(within(field("name")).getByText(/^Unknown/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Kitchen type" })).toHaveTextContent("Unknown");
  });

  it.each([
    ["NOT_SERVED", "Lookup is not available yet. Fill in the form yourself."],
    ["LOOKUP_UNAVAILABLE", "The lookup did not work this time. Fill in the form yourself, or try again."],
    ["RATE_LIMITED", "Too many lookups just now. Wait a minute, or fill in the form yourself."],
  ])("fails soft when the gateway answers %s", async (code, message) => {
    await lookUp("hotelkuusi.fi", {
      ...createMockApi(),
      lookupKitchenBrand: async () => {
        throw new ApiError(code, code);
      },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(message);
    expect(screen.getByLabelText("Kitchen name")).toHaveValue("");
    expect(within(field("name")).queryByText(FROM_CONTEXT)).not.toBeInTheDocument();
  });

  it("does not save a profile without a name or with a broken colour", async () => {
    const user = await lookUp("hotelkuusi.fi");
    const name = await screen.findByLabelText("Kitchen name");
    await user.clear(name);
    await user.type(screen.getByLabelText("Brand colours"), ", green");
    await user.click(screen.getByRole("button", { name: "Confirm and save" }));

    expect(screen.getByText("The kitchen needs a name.")).toBeVisible();
    expect(screen.getByText(/Write each colour as #/)).toBeVisible();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(localStorage.getItem("kitchen-brand")).toBeNull();
  });

  it("can be filled in by hand without a lookup", async () => {
    const user = userEvent.setup();
    renderApp("/onboarding");
    await user.click(await screen.findByRole("button", { name: "Fill in the form by hand" }));
    await user.type(screen.getByLabelText("Kitchen name"), "Keittio Testi");
    expect(document.querySelector("[data-note]")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Confirm and save" }));
    expect(await screen.findByLabelText("Saved kitchen profile")).toHaveTextContent("Keittio Testi");
    expect(JSON.parse(localStorage.getItem("kitchen-brand") ?? "null")).toMatchObject({
      logoUrl: null,
      kitchenType: null,
    });
  });

  it("never shows or saves a logo that is not https: or data:image/", async () => {
    const mock = createMockApi();
    const api: Api = {
      ...mock,
      lookupKitchenBrand: async (query) => {
        const lookup = await mock.lookupKitchenBrand(query);
        return { ...lookup, logoUrl: { ...lookup.logoUrl, value: "javascript:alert(1)" } };
      },
    };
    const user = await lookUp("hotelkuusi.fi", api);
    expect(await screen.findByLabelText("Kitchen name")).toHaveValue("Hotel Kuusi");
    expect(within(field("logoUrl")).queryByRole("img")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm and save" }));
    await screen.findByLabelText("Saved kitchen profile");
    expect(JSON.parse(localStorage.getItem("kitchen-brand") ?? "null")).toMatchObject({ logoUrl: null });
    expect(screen.queryByRole("img", { name: "Hotel Kuusi logo" })).not.toBeInTheDocument();
  });

  it("does not render an http: logo already in storage", async () => {
    localStorage.setItem(
      "kitchen-brand",
      JSON.stringify({ domain: "x.fi", name: "Old Kitchen", logoUrl: "http://x.fi/logo.png", colors: [] }),
    );
    renderApp("/onboarding");
    await screen.findByRole("heading", { level: 1, name: "Set up your kitchen" });
    expect(screen.queryByRole("img", { name: "Old Kitchen logo" })).not.toBeInTheDocument();
  });
});
