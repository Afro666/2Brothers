import { type Json, object } from "@/api/gateway-map";
import {
  mapAutoApproveLearning,
  mapDemand,
  mapKitchenSettings,
  mapList,
  mapMenuPlan,
  mapOwnProduct,
  mapRecipe,
  mapSharing,
  mapStock,
  mapSupplier,
  mapSupplierDemand,
  menuPlanBody,
  ownProductBody,
  recipeBody,
  settingsBody,
  stockCountBody,
  supplierBody,
} from "@/api/map-planning";
import type { Api, AuditActor } from "@/api/types";

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
  | "getKitchenSettings"
  | "saveKitchenSettings"
  | "getAutoApproveLearning"
>;

/** One JSON call to the gateway: `gatewayRequest` of api/http.ts with its base URL filled in. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;


/**
 * The supplier whose demand view this is (`VITE_GATEWAY_SUPPLIER_ID`, else `sup-valio`).
 * The gateway's consenting kitchens share with this id.
 */
const supplierId = (): string => import.meta.env.VITE_GATEWAY_SUPPLIER_ID || "sup-valio";

/**
 * The planning screens against the real gateway (gateway/kitchen_routes.py,
 * gateway/supplier_routes.py, `GET /auto-approve`). `kitchen` is `/v1/kitchens/{id}`.
 *
 * A write names the person in `X-User` when the screen knows the role; without it the web
 * server names the visitor (web/Caddyfile). Settings and sharing change only by an approver.
 */
export function createPlanningHttp(call: GatewayCall, kitchen: string): PlanningApi {
  const send = (method: "POST" | "PUT", path: string, body: Json, actor?: AuditActor) =>
    call(path, { method, headers: actor ? { "X-User": actor } : undefined, body: JSON.stringify(body) });
  const remove = async (path: string) => {
    await call(path, { method: "DELETE" });
  };
  const one = (list: string, id: string) => `${kitchen}/${list}/${encodeURIComponent(id)}`;
  /** Creates with POST when the draft has no id, else replaces with PUT. */
  const save = (list: string, id: string | undefined, body: Json) =>
    id ? send("PUT", one(list, id), body) : send("POST", `${kitchen}/${list}`, body);
  const window = (from: string, to: string) => `from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
  const stock = async () => mapStock(await call(`${kitchen}/stock`));
  const settings = async () => mapKitchenSettings(await call(`${kitchen}/settings`));
  // One key per count, kept after a failure: a retry must not store the count twice.
  const countKeys = new Map<string, string>();

  return {
    async listSuppliers() {
      return mapList(await call(`${kitchen}/suppliers`), "suppliers", "supplier_id", mapSupplier);
    },
    async saveSupplier(supplier) {
      return mapSupplier(await save("suppliers", supplier.id, supplierBody(supplier)));
    },
    deleteSupplier: (id) => remove(one("suppliers", id)),

    async listOwnProducts() {
      return mapList(await call(`${kitchen}/products`), "products", "product_id", mapOwnProduct);
    },
    async saveOwnProduct(product) {
      // The stored row says which pack measure the gateway has; the form does not carry it.
      const stored = product.id ? object(await call(one("products", product.id)), "an own product") : null;
      return mapOwnProduct(await save("products", product.id, ownProductBody(product, stored)));
    },
    deleteOwnProduct: (id) => remove(one("products", id)),

    async listRecipes() {
      return mapList(await call(`${kitchen}/recipes`), "recipes", "recipe_id", mapRecipe);
    },
    async saveRecipe(recipe) {
      // The stored row has each ingredient's yield; the form does not carry it.
      const stored = recipe.id ? object(await call(one("recipes", recipe.id)), "a recipe") : null;
      return mapRecipe(await save("recipes", recipe.id, recipeBody(recipe, stored)));
    },
    deleteRecipe: (id) => remove(one("recipes", id)),

    async getMenuPlan(week) {
      return mapMenuPlan(await call(one("menu-plans", week)));
    },
    async saveMenuPlan(week, entries) {
      return mapMenuPlan(await send("PUT", one("menu-plans", week), menuPlanBody(entries)));
    },

    getStock: stock,
    async submitStockCount(counts, actor) {
      const units = new Map((await stock()).map((item) => [item.productId, item.unit]));
      const identity = JSON.stringify(counts);
      // getRandomValues, not randomUUID: it also works on a plain-HTTP address.
      const key =
        countKeys.get(identity) ??
        Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
      countKeys.set(identity, key);
      await send(
        "POST",
        `${kitchen}/stock-counts`,
        stockCountBody(counts, units, new Date().toISOString(), key),
        actor,
      );
      // Stored: the same numbers counted again later are a new count.
      countKeys.delete(identity);
      return stock();
    },

    async getDemand(from, to) {
      return mapDemand(await call(`${kitchen}/demand?${window(from, to)}`));
    },

    async getSharing() {
      return mapSharing(await call(`${kitchen}/sharing`));
    },
    async setSharing(supplierId, shared, actor) {
      return mapSharing(
        await send("PUT", `${kitchen}/sharing`, { supplier_id: supplierId, share_forecast: shared }, actor),
      );
    },
    async getSupplierDemand(from, to) {
      return mapSupplierDemand(
        await call(`/v1/suppliers/${encodeURIComponent(supplierId())}/demand?${window(from, to)}`),
      );
    },

    getKitchenSettings: settings,
    async saveKitchenSettings(next, actor) {
      const before = await settings();
      const body = settingsBody(before, next);
      if (Object.keys(body).length === 0) return before;
      return mapKitchenSettings(await send("PUT", `${kitchen}/settings`, body, actor));
    },

    async getAutoApproveLearning() {
      return mapAutoApproveLearning(await call(`${kitchen}/auto-approve`));
    },
  };
}
