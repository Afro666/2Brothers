import { mapNutrition, mapRecipeNutrition } from "@/api/map-nutrition";
import { linkWordBody, mapKitchenWords } from "@/api/map-words";
import type { Api } from "@/api/types";

type NutritionApi = Pick<Api, "getRecipeNutrition" | "getNutrition" | "getKitchenWords" | "linkWord" | "forgetWord">;

/** One JSON call to the gateway: `gatewayRequest` of api/http.ts with its base URL filled in. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

/**
 * Nutrition from the label data (gateway/nutrition_routes.py) and the kitchen's own words
 * (gateway/memory.py) against the real gateway. `kitchen` is `/v1/kitchens/{id}`.
 *
 * The two word writes need a person who is not a viewer; the web server names the visitor
 * (web/Caddyfile), and the gateway's refusal is passed on as it is.
 */
export function createNutritionHttp(call: GatewayCall, kitchen: string): NutritionApi {
  return {
    async getRecipeNutrition(recipeId) {
      return mapRecipeNutrition(await call(`${kitchen}/recipes/${encodeURIComponent(recipeId)}/nutrition`));
    },
    async getNutrition(from, to) {
      return mapNutrition(
        await call(`${kitchen}/nutrition?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
      );
    },
    async getKitchenWords() {
      return mapKitchenWords(await call(`${kitchen}/aliases`));
    },
    async linkWord(phrase, productId) {
      await call(`${kitchen}/aliases`, { method: "PUT", body: JSON.stringify(linkWordBody(phrase, productId)) });
    },
    async forgetWord(phrase) {
      await call(`${kitchen}/aliases?phrase=${encodeURIComponent(phrase)}`, { method: "DELETE" });
    },
  };
}
