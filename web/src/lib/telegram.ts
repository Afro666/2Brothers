// Telegram's published web-view protocol, typed here: no Telegram script or package is loaded.
interface TelegramWebApp {
  ready(): void;
  expand(): void;
  close(): void;
}

declare global {
  interface Window {
    /** Set by Telegram's telegram-web-app.js when a host page loads it. */
    Telegram?: { WebApp?: TelegramWebApp };
    /** Injected by Telegram's Android and iOS web views; telegram-web-app.js itself posts to it. */
    TelegramWebviewProxy?: { postEvent(eventType: string, eventData: string): void };
  }
}

const LAUNCH_KEY = "2brothers.telegram-launch";

// Read once at load, before the router rewrites the address: later pages no longer carry the launch hash.
const launched = rememberLaunch();

function rememberLaunch(): boolean {
  if (typeof window === "undefined") return false;
  const fromHash = window.location.hash.includes("tgWebAppData=");
  try {
    if (fromHash) sessionStorage.setItem(LAUNCH_KEY, "1");
    return fromHash || sessionStorage.getItem(LAUNCH_KEY) === "1";
  } catch {
    return fromHash;
  }
}

/** True when the page runs as a Telegram Mini App. */
export function inTelegram(): boolean {
  return Boolean(window.Telegram?.WebApp || window.TelegramWebviewProxy || launched);
}

function call(method: "ready" | "expand" | "close"): void {
  try {
    const webApp = window.Telegram?.WebApp;
    if (webApp) webApp[method]();
    else window.TelegramWebviewProxy?.postEvent(`web_app_${method}`, "{}");
  } catch {
    // A failed Telegram call must never break the page or hide the approval result.
  }
}

export function readyTelegram(): void {
  call("ready");
  call("expand");
}

export function closeTelegram(): void {
  call("close");
}
