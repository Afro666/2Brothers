import { type Json, object } from "@/api/gateway-map";
import {
  mapAutoApproveLearning,
  mapDemand,
  mapKitchenSettings,
  mapList,
  mapMenuPlan,
  mapOwnProduct,
  mapPlanProposal,
  mapRecipe,
  mapSharing,
  mapStock,
  mapSupplier,
  mapSupplierDemand,
  menuPlanBody,
  ownProductBody,
  planProposalBody,
  recipeBody,
  settingsBody,
  stockCountBody,
  supplierBody,
} from "@/api/map-planning";
import { SUPPLIER_ID } from "@/api/supplier-id";
import type { Api, AuditActor } from "@/api/types";
import { randomHex } from "@/lib/random-id";

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
  | "proposeOrderForPlan"
  | "getSharing"
  | "setSharing"
  | "getSupplierDemand"
  | "getKitchenSettings"
  | "saveKitchenSettings"
  | "getAutoApproveLearning"
>;

/** One JSON call to the gateway: `gatewayRequest` of api/http.ts with its base URL filled in. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

/** The supplier whose demand view this is (api/supplier-id.ts); re-exported for api/http.ts. */
export { SUPPLIER_ID };

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
  // One key per plan window, kept after a failure: a new key could create a second proposal.
  const planKeys = new Map<string, string>();
  const newKey = () => randomHex(16);

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
      const key = countKeys.get(identity) ?? newKey();
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

    async proposeOrderForPlan(from, to, requestedDate) {
      const identity = JSON.stringify([from, to, requestedDate]);
      const key = planKeys.get(identity) ?? newKey();
      planKeys.set(identity, key);
      const proposal = mapPlanProposal(
        await send("POST", `${kitchen}/proposals`, planProposalBody(from, to, requestedDate, key)),
      );
      // Created: asking again later (after a new count or a changed plan) is a new proposal.
      planKeys.delete(identity);
      return proposal;
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
        await call(`/v1/suppliers/${encodeURIComponent(SUPPLIER_ID)}/demand?${window(from, to)}`),
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
