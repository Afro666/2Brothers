/**
 * The catalog supplier (the demo's Valio). The gateway's consenting kitchens share with this id.
 * `VITE_GATEWAY_SUPPLIER_ID` names another supplier; without it the demo's `sup-valio`.
 */
export const SUPPLIER_ID: string = import.meta.env.VITE_GATEWAY_SUPPLIER_ID || "sup-valio";
