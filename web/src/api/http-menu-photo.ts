import { type Json, object, rows } from "@/api/gateway-map";
import { blobToBase64 } from "@/api/http-shelf";
import type { Api, MenuPhotoDish, MenuPhotoRead } from "@/api/types";
import { ApiError } from "@/api/types";
import { randomHex } from "@/lib/random-id";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

const STATUSES: readonly MenuPhotoDish["status"][] = ["MATCHED", "NOT_KNOWN"];
const NO_PROPOSAL: readonly NonNullable<MenuPhotoRead["noProposalReason"]>[] = ["NOTHING_NEEDED", "NOT_SIZED"];
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

const textOrNull = (value: unknown): string | null => (typeof value === "string" && value ? value : null);

/**
 * One dish. Unknown is never a number or a recipe: a NOT_KNOWN dish keeps no recipe, and
 * only a MATCHED dish can be in the proposal, whatever the gateway sent.
 */
export function mapMenuDish(raw: Json): MenuPhotoDish {
  const status = STATUSES.find((known) => known === raw.status) ?? invalid("a menu dish status");
  if (typeof raw.dish !== "string") invalid("a menu dish name");
  const matched = status === "MATCHED";
  const recipeId = matched ? textOrNull(raw.recipe_id) : null;
  if (matched && !recipeId) invalid("a matched dish without a recipe");
  const covers = Number.isInteger(raw.covers) && (raw.covers as number) >= 0 ? (raw.covers as number) : null;
  const day = typeof raw.day === "string" && DATE.test(raw.day) ? raw.day : null;
  return {
    day,
    dish: raw.dish,
    covers,
    recipeId,
    recipeName: matched ? textOrNull(raw.recipe_name) : null,
    status,
    inProposal: matched && raw.in_proposal === true,
  };
}

/** `POST /v1/kitchens/{k}/menu-photo` (docs/contract.md, "Plan from a menu photo"). */
export function mapMenuPhoto(body: unknown): MenuPhotoRead {
  const raw = object(body, "the menu photo answer");
  if (typeof raw.model !== "string" || !raw.model) invalid("the menu photo model");
  let proposal: MenuPhotoRead["proposal"] = null;
  if (raw.proposal != null) {
    const made = object(raw.proposal, "the menu photo proposal");
    const id = textOrNull(made.proposal_id) ?? invalid("the menu photo proposal id");
    proposal = { id, status: textOrNull(made.status) ?? "READY" };
  }
  const reason = NO_PROPOSAL.find((known) => known === raw.no_proposal_reason) ?? null;
  return {
    model: raw.model,
    durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : null,
    from: typeof raw.from === "string" ? raw.from : "",
    to: typeof raw.to === "string" ? raw.to : "",
    dishes: rows(body, "dishes").map(mapMenuDish),
    proposal,
    noProposalReason: proposal ? null : reason,
  };
}

/**
 * "Plan from a menu photo" against the real gateway (#1136, gateway route by the agent side).
 * The gateway has Nemotron 3.5 Super VL read the menu, matches dishes to recipes and makes a
 * menu-plan proposal that a person approves in the inbox. Nothing is ordered here.
 */
export function createMenuPhotoHttp(call: GatewayCall, kitchen: string): Pick<Api, "readMenuPhoto"> {
  return {
    async readMenuPhoto(photo, window, actor) {
      const body = {
        image_base64: await blobToBase64(photo),
        from: window.from,
        to: window.to,
        ...(window.requestedDate ? { requested_date: window.requestedDate } : {}),
        // A new key per photo: a repeat of the same call makes no second proposal.
        idempotency_key: `web-menu-photo:${randomHex(16)}`,
      };
      try {
        return mapMenuPhoto(
          await call(`${kitchen}/menu-photo`, { method: "POST", headers: { "X-User": actor }, body: JSON.stringify(body) }),
        );
      } catch (error) {
        // NOTHING_MATCHED carries the dishes read, so the person sees what was not known.
        if (error instanceof ApiError && error.code === "NOTHING_MATCHED" && Array.isArray(error.details.dishes)) {
          const dishes = error.details.dishes
            .filter((dish): dish is Json => typeof dish === "object" && dish !== null && typeof (dish as Json).dish === "string")
            .map((dish) => mapMenuDish({ ...dish, status: "NOT_KNOWN" }));
          throw new ApiError(error.code, error.message, { ...error.details, dishes }, error.status);
        }
        throw error;
      }
    },
  };
}
