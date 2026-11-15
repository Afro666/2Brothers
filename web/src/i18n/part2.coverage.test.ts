import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { ATLAS_INDEX_TYPES, ATLAS_LABELS, ATLAS_SERIES_NAMES, ATLAS_VERDICTS } from "@/components/purchasing/atlas-card";
import { MODEL_USAGE_LABELS } from "@/components/purchasing/model-usage-card";
import { NEMOTRON_ALSO, NEMOTRON_JOBS } from "@/components/purchasing/nemotron-jobs-card";
import { CHOOSE_ERRORS } from "@/components/purchasing/option-compare";
import { CHIP_TEXTS } from "@/lib/proposal-checks";
import { MATCH_TEXT, REPLAN_ERROR_TEXT } from "@/components/purchasing/recall-lines";
import { RISK_META } from "@/components/purchasing/risk-badge";
import { STATUS_META } from "@/components/purchasing/status-badge";
import { URGENCY_META } from "@/components/purchasing/urgency-badge";
import { collectFinnishDictionaries } from "@/lib/i18n";
import { RECALL_SENTENCES } from "@/components/purchasing/recall-panel";

const PART2_FILES = [
  "pages/requests.tsx",
  "pages/live-buyer.tsx",
  "pages/live-approvals.tsx",
  "pages/approvals.tsx",
  "pages/orders.tsx",
  "pages/order-detail.tsx",
  "components/purchasing/approval-card.tsx",
  "components/purchasing/option-compare.tsx",
  "components/purchasing/recall-lines.tsx",
  "components/purchasing/recall-panel.tsx",
  "components/purchasing/order-resolution-panel.tsx",
  "components/purchasing/chef-request-box.tsx",
  "components/purchasing/order-lines-table.tsx",
  "components/purchasing/proposal-lines.tsx",
  "components/purchasing/mandate-summary.tsx",
  "components/purchasing/mov-progress.tsx",
  "components/purchasing/risk-badge.tsx",
  "components/purchasing/status-badge.tsx",
  "components/purchasing/urgency-badge.tsx",
  "components/purchasing/model-usage-card.tsx",
  "components/purchasing/atlas-card.tsx",
  "components/purchasing/nemotron-jobs-card.tsx",
  "components/purchasing/model-trace-panel.tsx",
];

describe("part 2 translations", () => {
  it("has a Finnish entry for every translated literal and metadata label", () => {
    const files = import.meta.glob("../i18n/fi/*.ts", { eager: true }) as Record<
      string,
      { default: Record<string, string> }
    >;
    const dictionary = collectFinnishDictionaries(files);
    const missing: string[] = [];
    for (const file of PART2_FILES) {
      const source = readFileSync(resolve(process.cwd(), "src", file), "utf8");
      for (const match of source.matchAll(/\bt\(\s*"((?:\\.|[^"\\])*)"/g)) {
        const text = JSON.parse(`"${match[1]}"`) as string;
        if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`${file}: ${text}`);
      }
    }
    const dynamicTexts = [
      ...[RISK_META, STATUS_META, URGENCY_META].flatMap((metadata) =>
        Object.values(metadata).flatMap((meta) => [meta.label, meta.meaning]),
      ),
      ...Object.values(CHOOSE_ERRORS),
      ...CHIP_TEXTS,
      ...Object.values(MATCH_TEXT),
      ...Object.values(REPLAN_ERROR_TEXT),
      ...RECALL_SENTENCES,
      "The replacement order could not be prepared.",
      ...Object.values(MODEL_USAGE_LABELS),
      ...Object.values(ATLAS_LABELS),
      ...Object.values(ATLAS_INDEX_TYPES),
      ...Object.values(ATLAS_VERDICTS),
      ...Object.values(ATLAS_SERIES_NAMES),
      ...NEMOTRON_JOBS.flatMap((job) => [job.name, job.text, job.link]),
      ...NEMOTRON_ALSO.flatMap((row) => [row.text, row.link]),
    ];
    for (const text of dynamicTexts) {
      if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`dynamic: ${text}`);
    }
    expect(missing).toEqual([]);
  });
});
