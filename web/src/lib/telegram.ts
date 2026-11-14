export interface TelegramWebApp {
  ready(): void;
  expand(): void;
  close(): void;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export function getTelegramWebApp(): TelegramWebApp | null {
  return typeof window === "undefined" ? null : (window.Telegram?.WebApp ?? null);
}
