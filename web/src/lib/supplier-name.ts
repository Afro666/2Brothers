/**
 * A supplier's name for people. The kitchen's own supplier rows win; the catalog supplier
 * (Valio Aimo, `sup-valio`) has a known name even when a kitchen has no row for it, so a
 * person never reads a raw id such as "sup-valio". An unknown id stays as it is.
 */
const KNOWN: Record<string, string> = { "sup-valio": "Valio Aimo" };

export function supplierName(id: string, names: Map<string, string>): string {
  return names.get(id) || KNOWN[id] || id;
}
