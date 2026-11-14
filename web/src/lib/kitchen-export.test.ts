import { describe, expect, it } from "vitest";

import { csvCell, kitchenExportCsv } from "@/lib/kitchen-export";

describe("kitchen export CSV", () => {
  it("quotes cells, preserves unknowns and neutralizes spreadsheet formulas", () => {
    expect(csvCell('hello, "world"')).toBe('"hello, ""world"""');
    expect(csvCell(null)).toBe('"unknown"');
    expect(csvCell("normal word")).toBe('"normal word"');
    expect(csvCell("PROD-42")).toBe('"PROD-42"');
    for (const formula of ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\t=1+1", "\r=1+1", "  =1+1", "-1", "@x", "-PROD-42", "\tproduct", "\rproduct"]) {
      expect(csvCell(formula)).toBe(`"'${formula.replaceAll('"', '""')}"`);
    }
  });

  it("orders records by type and sanitizes their visible cells", () => {
    const csv = kitchenExportCsv({
      orders: [],
      proposals: [],
      audit: [{ id: "=cmd", at: null, kind: "other", actor: "human", summary: '+SUM("A1")', reason: "test" }],
    });
    const lines = csv.split("\r\n");
    expect(lines[0]).toBe('"record_type","id","at","status","summary","data"');
    expect(lines).toHaveLength(2);
    expect(lines[1]).toContain('"audit","\'=cmd","unknown"');
    expect(lines[1]).toContain('"\'+SUM(""A1"")"');
  });
});
