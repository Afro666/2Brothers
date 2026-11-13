import { ApiError, type Api, type AuditActor, type Draft, type StockCount } from "@/api/types";
import { isoWeekOf } from "@/lib/week";
import { mandate } from "@/mocks/milk-case";
import {
  planningMenu,
  planningOwnProducts,
  planningRecipes,
  planningSharing,
  planningStock,
  planningSupplierDemand,
  planningSuppliers,
} from "@/mocks/planning";
import type { AuditEvent, DemandLine, SharingConsent, SupplierDemandRow } from "@/types";

type PlanningApi = Pick<
  Api,
  | "listSuppliers"
  | "saveSupplier"
  | "deleteSupplier"
  | "listOwnProducts"
  | "saveOwnProduct"
  | "deleteOwnProduct"
  | "listRecipes"
  | "saveRecipe"
  | "deleteRecipe"
  | "getMenuPlan"
  | "saveMenuPlan"
  | "getStock"
  | "submitStockCount"
  | "getDemand"
  | "getSharing"
  | "setSharing"
  | "getSupplierDemand"
>;

type AuditRecorder = (event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason">) => void;

const copy = <T>(value: T): T => structuredClone(value);

function requiredName(name: string): void {
  if (!name.trim()) throw new ApiError("INVALID", "Name must not be blank.");
}

function round3(value: number): number {
  return Math.round((value + Number.EPSILON) * 1000) / 1000;
}

export function createPlanningMock(recordAudit: AuditRecorder): PlanningApi {
  let suppliers = copy(planningSuppliers);
  let ownProducts = copy(planningOwnProducts);
  let recipes = copy(planningRecipes);
  let menu = copy(planningMenu);
  let stock = copy(planningStock);
  let sharing = copy(planningSharing);
  let nextId = 1;

  function makeId(prefix: string): string {
    const id = `${prefix}-${nextId}`;
    nextId += 1;
    return id;
  }

  function saveById<T extends { id: string }>(rows: T[], draft: Draft<T>, prefix: string): T {
    const saved = { ...copy(draft), id: draft.id ?? makeId(prefix) } as T;
    const existing = rows.findIndex((row) => row.id === saved.id);
    if (draft.id && existing < 0) throw new ApiError("NOT_FOUND", `${prefix} ${draft.id} was not found.`);
    if (existing < 0) rows.push(saved);
    else rows[existing] = saved;
    return copy(saved);
  }

  function deleteById<T extends { id: string }>(rows: T[], id: string, kind: string): void {
    const index = rows.findIndex((row) => row.id === id);
    if (index < 0) throw new ApiError("NOT_FOUND", `${kind} ${id} was not found.`);
    rows.splice(index, 1);
  }

  function getDemand(from: string, to: string): DemandLine[] {
    const totals = new Map<string, DemandLine & { parts: string[] }>();
    for (const entry of menu) {
      if (entry.date < from || entry.date > to) continue;
      const recipe = recipes.find((candidate) => candidate.id === entry.recipeId);
      if (!recipe) continue;
      for (const item of recipe.items) {
        const key = `${entry.date}\u0000${item.productId}`;
        const need = entry.covers * item.qtyPerPortion;
        const current = totals.get(key);
        if (current) {
          current.need += need;
          current.parts.push(`${entry.covers} covers x ${item.qtyPerPortion} ${item.unit} (${recipe.name})`);
        } else {
          totals.set(key, {
            productId: item.productId,
            productName: item.productName,
            unit: item.unit,
            date: entry.date,
            need,
            why: "",
            parts: [`${entry.covers} covers x ${item.qtyPerPortion} ${item.unit} (${recipe.name})`],
          });
        }
      }
    }
    return [...totals.values()].map(({ parts, ...line }) => ({
      ...line,
      need: round3(line.need),
      why: parts.join("; "),
    }));
  }

  /** One row per current supplier; a supplier that was never asked shares nothing. */
  function sharingRows(): SharingConsent[] {
    return copy(
      suppliers.map(
        (supplier) =>
          sharing.find((row) => row.supplierId === supplier.id) ?? { supplierId: supplier.id, shared: false },
      ),
    );
  }

  return {
    async listSuppliers() {
      return copy(suppliers);
    },
    async saveSupplier(supplier) {
      requiredName(supplier.name);
      return saveById(suppliers, supplier, "SUP");
    },
    async deleteSupplier(id) {
      if (ownProducts.some((product) => product.supplierId === id)) {
        const name = suppliers.find((supplier) => supplier.id === id)?.name ?? id;
        throw new ApiError("IN_USE", `${name} still supplies some of your own products. Move or delete those first.`);
      }
      deleteById(suppliers, id, "Supplier");
      sharing = sharing.filter((consent) => consent.supplierId !== id);
    },
    async listOwnProducts() {
      return copy(ownProducts);
    },
    async saveOwnProduct(product) {
      requiredName(product.name);
      return saveById(ownProducts, product, "OWN");
    },
    async deleteOwnProduct(id) {
      if (recipes.some((recipe) => recipe.items.some((item) => item.productId === id))) {
        const name = ownProducts.find((product) => product.id === id)?.name ?? id;
        throw new ApiError("IN_USE", `${name} is used in a recipe. Remove it from the recipe first.`);
      }
      deleteById(ownProducts, id, "Own product");
    },
    async listRecipes() {
      return copy(recipes);
    },
    async saveRecipe(recipe) {
      requiredName(recipe.name);
      return saveById(recipes, recipe, "REC");
    },
    async deleteRecipe(id) {
      if (menu.some((entry) => entry.recipeId === id)) {
        const name = recipes.find((recipe) => recipe.id === id)?.name ?? id;
        throw new ApiError("IN_USE", `${name} is on the menu plan. Take it off the plan first.`);
      }
      deleteById(recipes, id, "Recipe");
    },
    async getMenuPlan(week) {
      return copy(menu.filter((entry) => isoWeekOf(entry.date) === week));
    },
    async saveMenuPlan(week, entries) {
      for (const entry of entries) {
        if (!Number.isInteger(entry.covers) || entry.covers < 0) {
          throw new ApiError("INVALID", "Menu covers must be a whole number greater than or equal to zero.");
        }
      }
      const saved = entries.map((entry) => ({ ...copy(entry), id: entry.id ?? makeId("MENU") }));
      if (saved.some((entry) => isoWeekOf(entry.date) !== week)) {
        throw new ApiError("INVALID", "Every menu entry date must fall in the requested ISO week.");
      }
      menu = [...menu.filter((entry) => isoWeekOf(entry.date) !== week), ...saved];
      return copy(saved);
    },
    async getStock() {
      return copy(stock);
    },
    async submitStockCount(counts: StockCount[], actor: AuditActor) {
      const countedAt = new Date().toISOString();
      for (const count of counts) {
        const item = stock.find((row) => row.productId === count.productId);
        if (!item) throw new ApiError("NOT_FOUND", `Stock product ${count.productId} was not found.`);
        item.onHand = count.onHand;
        item.countedAt = countedAt;
      }
      const unknown = counts.filter((count) => count.onHand === null).length;
      recordAudit({
        kind: "stock",
        actor,
        summary: `Stock count submitted for ${counts.length} products`,
        reason: `${counts.length - unknown} counted and ${unknown} unknown.`,
      });
      return copy(stock);
    },
    async getDemand(from, to) {
      return getDemand(from, to);
    },
    async getSharing() {
      return sharingRows();
    },
    async setSharing(supplierId, shared, actor) {
      const supplier = suppliers.find((row) => row.id === supplierId);
      if (!supplier) throw new ApiError("NOT_FOUND", `Sharing supplier ${supplierId} was not found.`);
      const consent = sharing.find((row) => row.supplierId === supplierId);
      if (consent) consent.shared = shared;
      else sharing.push({ supplierId, shared });
      const supplierName = supplier.name;
      recordAudit({
        kind: "forecast_share",
        actor,
        summary: `Forecast sharing ${shared ? "turned on" : "turned off"} for ${supplierName}`,
        reason: shared
          ? `${supplierName} can now see what this kitchen expects to need.`
          : `${supplierName} no longer sees this kitchen's forecast.`,
      });
      return sharingRows();
    },
    async getSupplierDemand(from, to) {
      const ownNeed = getDemand(from, to);
      const sharesWithValio = sharing.some((consent) => consent.supplierId === "SUP-VALIO" && consent.shared);
      return copy(
        planningSupplierDemand
          .filter((row) => row.date >= from && row.date <= to)
          .map((base): SupplierDemandRow => {
            const own = sharesWithValio
              ? ownNeed.find((line) => line.date === base.date && line.productId === base.productId)
              : undefined;
            const byKitchen = [...base.byKitchen];
            if (own) {
              byKitchen.push({
                kitchenId: "K00",
                kitchenName: `K00 ${mandate.restaurant}`,
                demand: Math.ceil(own.need),
              });
            }
            const forecastDemand = byKitchen.reduce((sum, kitchen) => sum + kitchen.demand, 0);
            const risk =
              base.available === null
                ? "UNKNOWN"
                : base.available < forecastDemand
                  ? "SHORT"
                  : base.available < forecastDemand * 1.15
                    ? "AT_RISK"
                    : "COVERED";
            return {
              ...base,
              byKitchen,
              forecastDemand,
              kitchens: byKitchen.length,
              risk,
              suggestedBuy: base.available === null ? null : Math.max(0, forecastDemand - base.available),
            };
          }),
      );
    },
  };
}
