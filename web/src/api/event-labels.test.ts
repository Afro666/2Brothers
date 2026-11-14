import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { EVENT_KINDS, mapAudit } from "@/api/gateway-map";
import { CODE_LABELS, plainCode } from "@/lib/codes";
import { translate } from "@/lib/i18n";

/**
 * #1776: every event kind the Python code can write to the audit log has a plain label.
 * The kinds are read from the sources, so a new kind without a label fails here and
 * never reaches the activity list as a made-up or raw name. The label is the summary in
 * EVENT_KINDS, or the title `plainCode` gives a kind that `lib/codes.ts` names.
 */
const labelOf = (kind: string): string | undefined =>
  Object.hasOwn(EVENT_KINDS, kind)
    ? EVENT_KINDS[kind].summary
    : Object.hasOwn(CODE_LABELS, kind)
      ? CODE_LABELS[kind].title
      : undefined;
const REPO = resolve(process.cwd(), "..");
/** The folders whose code appends to the audit log. The Buyer's tool calls have their own labels (TOOL_VERBS). */
const FOLDERS = ["gateway", "monitor", "store", "demo"];
const KIND = "[a-z{}]+(?:[_.][a-z{}]+)*";

function pythonFiles(folder: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) return entry.name === "tests" || entry.name === "__pycache__" ? [] : pythonFiles(path);
    return entry.name.endsWith(".py") && !entry.name.startsWith("test_") ? [path] : [];
  });
}

/** The kinds one source file writes: `{kind: where}`. */
function kindsIn(source: string, file: string): Map<string, string> {
  const found = new Map<string, string>();
  const add = (kind: string) => {
    // `f"{name}_created"` (gateway/kitchen_routes.py): one kind per `crud(path, name, ...)`.
    if (kind.includes("{")) {
      for (const crud of source.matchAll(/\bcrud\(\s*["'][^"']+["'],\s*["']([a-z_]+)["']/g)) {
        found.set(kind.replace(/\{[a-z]+\}/, crud[1]), file);
      }
    } else found.set(kind, file);
  };
  // `gw._audit(kitchen_id, "kind", ...)`, `_audit_once(gw, kitchen_id, "kind", ...)`,
  // `_record(gw, kitchen_id, event_id, "kind", ...)`, `record(kitchen_id, "kind", ...)`, and
  // `run_in_threadpool(gateway._audit, kitchen_id, "kind", ...)`: the first text argument.
  const call = new RegExp(
    `(?:\\b_audit(?:_once)?|\\b_?record)[(,][^\\n]{0,120}?,\\s*f?(["'])(${KIND})\\1(\\s+if\\s+\\w+\\s+else\\s+(["'])(${KIND})\\4)?\\s*[,)]`,
    "g",
  );
  for (const match of source.matchAll(call)) {
    add(match[2]);
    if (match[5]) add(match[5]);
  }
  // An event written as a dict: `{"event_id": ..., "kind": "recall_check", ...}`; the older
  // rows carry `"type"` (`share_granted`, `recall.alert`). Only in a file that appends events.
  if (!/\bappend_event(?:_new)?\(/.test(source)) return found;
  const literal = new RegExp(
    `["'](?:kind|type)["']:\\s*(["'])([a-z]+(?:[_.][a-z]+)+)\\1(?:\\s+if\\s+\\w+\\s+else\\s+(["'])(${KIND})\\3)?`,
    "g",
  );
  for (const match of source.matchAll(literal)) {
    add(match[2]);
    if (match[4]) add(match[4]);
  }
  return found;
}

function emittedKinds(): Map<string, string> {
  const all = new Map<string, string>();
  for (const folder of FOLDERS) {
    for (const path of pythonFiles(join(REPO, folder))) {
      const file = path.slice(REPO.length + 1).replace(/\\/g, "/");
      for (const [kind, where] of kindsIn(readFileSync(path, "utf8"), file)) all.set(kind, where);
    }
  }
  return all;
}

describe("audit event labels (#1776)", () => {
  const emitted = emittedKinds();

  it("finds the kinds in the Python sources", () => {
    // A scan that finds little is a broken scan, not a clean result.
    expect(emitted.size).toBeGreaterThanOrEqual(60);
    for (const kind of [
      "approval_token_created", // gateway/app.py and gateway/tokens.py
      "proposal_changed", // gateway/change.py
      "signed_in", // the kind is on the line after `_audit(`
      "proposal_explanation_ready", // `'a' if result else 'b'`
      "proposal_explanation_failed",
      "kitchen_brief_read", // `run_in_threadpool(gateway._audit, ...)`
      "recipes_created", // `f"{name}_created"`
      "order_resolved", // a dict with "kind"
      "share_revoked", // a dict with "type"
      "recall.alert",
      "recall_replacement_proposed", // monitor/
      "demo_delivery_order_placed", // demo/
    ]) {
      expect(emitted.has(kind), kind).toBe(true);
    }
  });

  it("has a plain-English label for every kind the code can write", () => {
    const missing = [...emitted].filter(([kind]) => labelOf(kind) === undefined);
    expect(missing.map(([kind, file]) => `${kind} (${file})`)).toEqual([]);
  });

  it("has no label that reads as a raw code, and a Finnish text for each", () => {
    const fi = (text: string) => translate("fi", text);
    const noFinnish: string[] = [];
    for (const kind of new Set([...emitted.keys(), ...Object.keys(EVENT_KINDS)])) {
      const label = labelOf(kind);
      if (label === undefined) continue; // the test above names it
      expect(label, kind).not.toMatch(/^[a-z0-9]+(?:[_.][a-z0-9]+)+$/);
      expect(label, kind).toMatch(/^[A-Z]/);
      // What the pages do with a summary: `t(plainCode(summary, t))`.
      const [{ summary }] = mapAudit([{ event_id: "x", kind, actor: "system" }]);
      if (fi(plainCode(summary, fi)) === label) noFinnish.push(`${kind}: ${label}`);
    }
    expect(noFinnish).toEqual([]);
  });

  it("labels an event that has a type and no kind (share_granted, recall.alert)", () => {
    const [shared, recall] = mapAudit([
      { event_id: "s-1", type: "share_granted", supplier_id: "sup-valio", user: "human", at: "2026-11-14T04:24:39+00:00" },
      { event_id: "r-1", type: "recall.alert", run_id: "recall-monitor", at: "2026-11-14T05:00:00+00:00" },
    ]);
    expect(shared.summary).toBe(EVENT_KINDS.share_granted.summary);
    expect(shared.kind).toBe("forecast_share");
    expect(recall.summary).toBe(EVENT_KINDS["recall.alert"].summary);
  });
});
