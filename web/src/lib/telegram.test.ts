import { afterEach, describe, expect, it, vi } from "vitest";

/** A fresh copy of the module, so it reads the launch address again as on a new page load. */
async function load(hash = "") {
  window.history.replaceState(null, "", `/approvals${hash}`);
  vi.resetModules();
  return import("@/lib/telegram");
}

afterEach(() => {
  delete window.Telegram;
  delete window.TelegramWebviewProxy;
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("telegram", () => {
  it("is off in a normal browser", async () => {
    const telegram = await load();
    expect(telegram.inTelegram()).toBe(false);
    expect(() => telegram.closeTelegram()).not.toThrow();
  });

  it("uses Telegram.WebApp when the host page has it", async () => {
    const webApp = { ready: vi.fn(), expand: vi.fn(), close: vi.fn() };
    const postEvent = vi.fn();
    window.Telegram = { WebApp: webApp };
    window.TelegramWebviewProxy = { postEvent };
    const telegram = await load();

    expect(telegram.inTelegram()).toBe(true);
    telegram.readyTelegram();
    telegram.closeTelegram();
    expect(webApp.ready).toHaveBeenCalledTimes(1);
    expect(webApp.expand).toHaveBeenCalledTimes(1);
    expect(webApp.close).toHaveBeenCalledTimes(1);
    expect(postEvent).not.toHaveBeenCalled();
  });

  it("posts to the web view's proxy when there is no Telegram.WebApp", async () => {
    const postEvent = vi.fn();
    window.TelegramWebviewProxy = { postEvent };
    const telegram = await load();

    expect(telegram.inTelegram()).toBe(true);
    telegram.readyTelegram();
    telegram.closeTelegram();
    expect(postEvent.mock.calls).toEqual([
      ["web_app_ready", "{}"],
      ["web_app_expand", "{}"],
      ["web_app_close", "{}"],
    ]);
  });

  it("detects a launch from the address hash and remembers it for later pages", async () => {
    expect((await load("#tgWebAppData=query_id%3DAAA&tgWebAppVersion=8.0")).inTelegram()).toBe(true);
    // The next page load has no hash any more: the session still knows it is inside Telegram.
    expect((await load()).inTelegram()).toBe(true);
    sessionStorage.clear();
    expect((await load()).inTelegram()).toBe(false);
  });

  it("still detects the hash when session storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect((await load("#tgWebAppData=x")).inTelegram()).toBe(true);
  });

  it("never throws when closing fails", async () => {
    window.TelegramWebviewProxy = {
      postEvent: () => {
        throw new Error("gone");
      },
    };
    const telegram = await load();
    expect(() => telegram.closeTelegram()).not.toThrow();
    window.Telegram = {
      WebApp: {
        ready: vi.fn(),
        expand: vi.fn(),
        close: () => {
          throw new Error("gone");
        },
      },
    };
    expect(() => telegram.closeTelegram()).not.toThrow();
  });
});
