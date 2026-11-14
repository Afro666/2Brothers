import { useEffect, useState } from "react";

import { useOptionalApi } from "@/api";
import type { Api, BrandLogo } from "@/api/types";
import { safeLogoUrl } from "@/lib/kitchen-brand";

const BATCH = 50; // the route takes at most 50 names
const MAX_NAME = 100; // a longer name makes the route answer 422 for the whole batch

interface Loader {
  cache: Map<string, Promise<BrandLogo | null>>;
  waiting: Map<string, (logo: BrandLogo | null) => void>;
  timer: ReturnType<typeof setTimeout> | null;
}

const loaders = new WeakMap<Api, Loader>();

function flush(api: Api, loader: Loader) {
  loader.timer = null;
  const waiting = [...loader.waiting];
  loader.waiting.clear();
  for (let start = 0; start < waiting.length; start += BATCH) {
    const part = waiting.slice(start, start + BATCH);
    const names = part.map(([name]) => name);
    (api.listBrandLogos?.(names) ?? Promise.resolve([]))
      .then((rows) => {
        const byName = new Map(rows.map((row) => [row.brand, row]));
        for (const [name, resolve] of part) resolve(byName.get(name) ?? null);
      })
      // No logo list: every picture keeps its kind tile. Not asked again on this page.
      .catch(() => {
        for (const [, resolve] of part) resolve(null);
      });
  }
}

/**
 * One brand's logo row. The brands asked in the same moment (one list of products) go
 * to the gateway in one call; each brand is asked once per page.
 */
export function loadBrandLogo(api: Api, brand: string): Promise<BrandLogo | null> {
  // Never sent: one over-long name would drop the logos of every brand in its batch.
  if (brand.length > MAX_NAME) return Promise.resolve(null);
  let loader = loaders.get(api);
  if (!loader) {
    loader = { cache: new Map(), waiting: new Map(), timer: null };
    loaders.set(api, loader);
  }
  const known = loader.cache.get(brand);
  if (known) return known;
  const current = loader;
  const promise = new Promise<BrandLogo | null>((resolve) => {
    current.waiting.set(brand, resolve);
  });
  current.cache.set(brand, promise);
  current.timer ??= setTimeout(() => flush(api, current), 0);
  return promise;
}

/** The brand's logo when one is known and safe to show; null otherwise (and while loading). */
export function useBrandLogo(brand: string | null | undefined): BrandLogo | null {
  const api = useOptionalApi();
  const name = brand?.trim() ?? "";
  const [state, setState] = useState<{ name: string; logo: BrandLogo | null }>({ name: "", logo: null });
  useEffect(() => {
    if (!api?.listBrandLogos || !name) return;
    let active = true;
    void loadBrandLogo(api, name).then((logo) => {
      if (active) setState({ name, logo });
    });
    return () => {
      active = false;
    };
  }, [api, name]);
  const logo = state.name === name ? state.logo : null;
  return logo?.status === "found" && safeLogoUrl(logo.logoUrl)?.startsWith("https://") ? logo : null;
}
