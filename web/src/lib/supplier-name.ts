/** The name shown for a supplier id: the kitchen's own row, else "Valio Aimo" for sup-valio, else the raw id. */
export function supplierName(names: ReadonlyMap<string, string>, supplierId: string): string {
  return names.get(supplierId) ?? (supplierId.toLowerCase() === "sup-valio" ? "Valio Aimo" : supplierId);
}
