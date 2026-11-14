import { ApiError, type Api, type KitchenAlias, type UnknownWord } from "@/api/types";

type WordsApi = Pick<Api, "getKitchenWords" | "linkWord" | "forgetWord">;

/** The gateway's `normalise` (gateway/memory.py): lower case, punctuation to spaces, single spaces. */
function normalise(phrase: string): string {
  return phrase
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s%]/gu, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .slice(0, 80);
}

const sampleAliases: KitchenAlias[] = [
  {
    phrase: "blue milk",
    productId: "463335",
    productName: "Valio Eila 3 % lactose free milk drink 1 L",
    setBy: "Aino (approver)",
    uses: 4,
  },
];

const sampleUnknown: UnknownWord[] = [
  { phrase: "house milk", times: 3, firstAsked: "2026-11-10T07:12:00+00:00", lastAsked: "2026-11-13T06:48:00+00:00" },
  { phrase: "oat barista", times: 1, firstAsked: "2026-11-12T09:30:00+00:00", lastAsked: "2026-11-12T09:30:00+00:00" },
];

/** The kitchen's own words for the mock API. `getProducts` names the product a word is linked to. */
export function createWordsMock(getProducts: Api["getProducts"]): WordsApi {
  let aliases = structuredClone(sampleAliases);
  let unknown = structuredClone(sampleUnknown);
  return {
    async getKitchenWords() {
      return {
        aliases: structuredClone(aliases).sort((a, b) => a.phrase.localeCompare(b.phrase)),
        unknownItems: structuredClone(unknown).sort((a, b) => b.times - a.times),
      };
    },
    async linkWord(phrase, productId) {
      const key = normalise(phrase);
      if (key.length < 2) throw new ApiError("INVALID_REQUEST", "the phrase needs at least 2 characters", {}, 422);
      const [product] = await getProducts([productId]);
      if (!product) throw new ApiError("INVALID_REQUEST", "no such product for this kitchen", {}, 422);
      const before = aliases.find((alias) => alias.phrase === key);
      aliases = [
        ...aliases.filter((alias) => alias.phrase !== key),
        { phrase: key, productId, productName: product.names.en, setBy: "you", uses: before?.uses ?? 0 },
      ];
      // It is known now.
      unknown = unknown.filter((item) => item.phrase !== key);
    },
    async forgetWord(phrase) {
      const key = normalise(phrase);
      const total = aliases.length + unknown.length;
      if (aliases.some((alias) => alias.phrase === key)) aliases = aliases.filter((alias) => alias.phrase !== key);
      else unknown = unknown.filter((item) => item.phrase !== key);
      if (aliases.length + unknown.length === total) throw new ApiError("NOT_FOUND", "no such phrase", {}, 404);
    },
  };
}
