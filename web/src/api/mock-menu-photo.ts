import type { MenuPhotoDish, MenuPhotoRead } from "@/api/types";

/** The mock's pause before it answers, so the "reading" state shows as it does live. */
export const MENU_PHOTO_MOCK_DELAY_MS = 900;

/** The date `days` after `from` (`YYYY-MM-DD`). */
function addDays(from: string, days: number): string {
  const date = new Date(`${from}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/**
 * A sample of what the gateway answers for a typed menu of five dishes (docs/contract.md,
 * "Plan from a menu photo"): four match a mock recipe, one is not known. Monday to Friday
 * of the asked window.
 */
export function menuPhotoSample(from: string, to: string): MenuPhotoRead {
  const dish = (
    days: number,
    name: string,
    covers: number,
    recipe: { id: string; name: string } | null,
  ): MenuPhotoDish => ({
    day: addDays(from, days),
    dish: name,
    covers,
    recipeId: recipe?.id ?? null,
    recipeName: recipe?.name ?? null,
    status: recipe ? "MATCHED" : "NOT_KNOWN",
    inProposal: recipe !== null,
  });
  const soup = { id: "REC-SALMON-SOUP", name: "Salmon soup" };
  const pudding = { id: "REC-RICE-PUDDING", name: "Rice pudding" };
  return {
    model: "nemotron-3.5-super-vl",
    durationMs: 6100,
    from,
    to,
    dishes: [
      dish(0, "Salmon soup", 120, soup),
      dish(1, "Rice pudding", 90, pudding),
      dish(2, "Creamy salmon soup", 110, soup),
      dish(3, "Rice pudding with berries", 90, pudding),
      dish(4, "Reindeer stew", 80, null),
    ],
    proposal: { id: "PROP-MENU-PHOTO-1", status: "READY" },
    noProposalReason: null,
  };
}

/** The mock reads no photo: every photo gets the sample after a short pause. It orders nothing. */
export async function readMenuPhotoMock(_photo: Blob, window: { from: string; to: string }): Promise<MenuPhotoRead> {
  await new Promise((resolve) => setTimeout(resolve, MENU_PHOTO_MOCK_DELAY_MS));
  return menuPhotoSample(window.from, window.to);
}
