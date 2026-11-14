import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { ACTOR_LABEL, KIND_META } from "@/components/purchasing/audit-timeline";
import { EU_ALLERGENS } from "@/lib/allergens";
import { collectFinnishDictionaries } from "@/lib/i18n";
import { RISK_PLURALS } from "@/pages/demand";
import { GROUPS as FORECAST_GROUPS, TILES as FORECAST_TILES } from "@/pages/forecast";
import { DEMO_ERRORS, ELSEWHERE } from "@/pages/trust";
import { DEMAND_CLASSES } from "@/pages/settings/engine";
import { TYPES as KITCHEN_TYPES } from "@/pages/settings/kitchen";
import { EVENTS as NOTIFICATION_EVENTS } from "@/pages/settings/notifications";
import { GROUPS as PERMISSION_GROUPS } from "@/pages/settings/permissions";
import { SETTINGS_SECTIONS } from "@/pages/settings/sections";
import { ROLE_DETAILS } from "@/pages/settings/team";
import { SCOPES as TOKEN_SCOPES } from "@/pages/settings/tokens";

const TRANSLATED_FILES = [
  "pages/forecast.tsx",
  "pages/audit.tsx",
  "pages/trust.tsx",
  "pages/demand.tsx",
  "components/purchasing/audit-timeline.tsx",
  "components/purchasing/forecast-chart.tsx",
  "pages/settings/settings-page.tsx",
  "pages/settings/section.tsx",
  "pages/settings/sections.ts",
  "pages/settings/data-privacy.tsx",
  "pages/settings/developer.tsx",
  "pages/settings/engine.tsx",
  "pages/settings/kitchen.tsx",
  "pages/settings/notifications.tsx",
  "pages/settings/permissions.tsx",
  "pages/settings/team.tsx",
  "pages/settings/tokens.tsx",
];

const SETTINGS_FILES = TRANSLATED_FILES.filter(
  (file) => file.startsWith("pages/settings/") && !["section.tsx", "sections.ts"].includes(file.split("/").at(-1) ?? ""),
);

describe("part 4 Finnish coverage", () => {
  it("has a Finnish entry for every literal and data label passed to t", () => {
    const files = import.meta.glob("../i18n/fi/*.ts", { eager: true }) as Record<
      string,
      { default: Record<string, string> }
    >;
    const dictionary = collectFinnishDictionaries(files);
    const missing: string[] = [];

    for (const file of TRANSLATED_FILES) {
      const source = readFileSync(resolve(process.cwd(), "src", file), "utf8");
      for (const match of source.matchAll(/\bt\(\s*"((?:\\.|[^"\\])*)"/g)) {
        const text = JSON.parse(`"${match[1]}"`) as string;
        if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`${file}: ${text}`);
      }
    }

    for (const file of SETTINGS_FILES) {
      const source = readFileSync(resolve(process.cwd(), "src", file), "utf8");
      for (const tag of source.matchAll(/<SettingsSection\b([^>]*)>/gs)) {
        for (const match of tag[1].matchAll(/(?:title|description)="((?:\\.|[^"\\])*)"/g)) {
          const text = JSON.parse(`"${match[1]}"`) as string;
          if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`${file}: ${text}`);
        }
      }
    }

    const dynamicTexts = [
      ...FORECAST_GROUPS,
      ...FORECAST_TILES.flatMap((tile) => [tile.label, tile.hint]),
      ...Object.values(KIND_META).map((meta) => meta.label),
      ...Object.values(ACTOR_LABEL),
      ...Object.values(DEMO_ERRORS),
      ELSEWHERE,
      ...Object.values(RISK_PLURALS),
      ...SETTINGS_SECTIONS.map((section) => section.label),
      ...Object.values(ROLE_DETAILS),
      ...NOTIFICATION_EVENTS.flatMap((event) => [event.title, event.description]),
      ...PERMISSION_GROUPS.flatMap((group) => [group.title, group.description]),
      ...DEMAND_CLASSES.map((demandClass) => demandClass.description),
      ...KITCHEN_TYPES.map((type) => type.label),
      ...TOKEN_SCOPES.flatMap((scope) => [scope.title, scope.description]),
      ...EU_ALLERGENS.map((allergen) => allergen.name),
    ];
    for (const text of dynamicTexts) {
      if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`dynamic: ${text}`);
    }

    expect(missing).toEqual([]);
  });
});
