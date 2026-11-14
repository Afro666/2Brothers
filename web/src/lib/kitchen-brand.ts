import { useSyncExternalStore } from "react";

import type { KitchenBrandProfile } from "@/types";

/**
 * The profile a person confirmed on the onboarding page, kept per browser
 * until the gateway stores the kitchen profile. The app shell reads the logo from it.
 */
const STORAGE_KEY = "kitchen-brand";
const listeners = new Set<() => void>();
/** Used when storage is blocked: the profile then lasts until the page reloads. */
let memory: string | null = null;
let cache: { raw: string | null; profile: KitchenBrandProfile | null } = { raw: null, profile: null };

function rawProfile(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? memory;
  } catch {
    return memory;
  }
}

function read(): KitchenBrandProfile | null {
  const raw = rawProfile();
  if (raw === cache.raw) return cache.profile;
  let profile: KitchenBrandProfile | null = null;
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === "object" && typeof (parsed as KitchenBrandProfile).name === "string") {
      profile = parsed as KitchenBrandProfile;
    }
  } catch {
    // Not JSON: no profile.
  }
  cache = { raw, profile };
  return profile;
}

export function saveKitchenBrand(profile: KitchenBrandProfile) {
  const raw = JSON.stringify(profile);
  try {
    localStorage.setItem(STORAGE_KEY, raw);
  } catch {
    memory = raw;
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useKitchenBrand(): KitchenBrandProfile | null {
  return useSyncExternalStore(subscribe, read, () => null);
}
