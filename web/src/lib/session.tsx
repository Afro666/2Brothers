import { useNavigate } from "@tanstack/react-router";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { useApi } from "@/api";
import { SIGNED_OUT_EVENT } from "@/api/http";
import { dropKeptAnswers } from "@/lib/use-async";
import { ApiError, type Session } from "@/api/types";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { SignInPage } from "@/pages/sign-in";

interface SessionContextValue {
  status: "loading" | "signed-in" | "signed-out";
  session: Session | null;
  signInRevision: number;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  /** The session, null when signed out, undefined when `/v1/me` failed (the error screen shows). */
  reload(): Promise<Session | null | undefined>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const navigate = useNavigate();
  const initialLoadStarted = useRef(false);
  // A lookup that started before a newer sign-in or sign-out must not overwrite it.
  const reloadGeneration = useRef(0);
  const [status, setStatus] = useState<SessionContextValue["status"]>("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [signInRevision, setSignInRevision] = useState(0);
  const [failure, setFailure] = useState<Error | null>(null);

  const reload = useCallback(async () => {
    const generation = ++reloadGeneration.current;
    setStatus("loading");
    setFailure(null);
    try {
      const next = await api.getSession();
      if (generation !== reloadGeneration.current) return undefined;
      setSession(next);
      setStatus(next ? "signed-in" : "signed-out");
      return next;
    } catch (cause) {
      if (generation !== reloadGeneration.current) return undefined;
      if (cause instanceof ApiError && (cause.code === "UNAUTHENTICATED" || cause.status === 401)) {
        setSession(null);
        setStatus("signed-out");
        return null;
      }
      setFailure(cause instanceof Error ? cause : new Error(String(cause)));
      return undefined;
    }
  }, [api]);

  useEffect(() => {
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    void reload();
  }, [reload]);

  useEffect(() => {
    const signedOut = () => {
      setSession(null);
      setFailure(null);
      setStatus("signed-out");
    };
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
  }, []);

  async function signIn(email: string, password: string) {
    const next = await api.signIn(email, password);
    reloadGeneration.current += 1;
    setSession(next);
    setSignInRevision((revision) => revision + 1);
    setStatus("signed-in");
    await navigate({ to: "/" });
  }

  async function signOut() {
    reloadGeneration.current += 1;
    // Also for an api that signs out without a gateway write (the mock): nothing kept outlives the session.
    dropKeptAnswers();
    try {
      await api.signOut();
    } catch {
      setFailure(null);
      setSession(null);
      setStatus("signed-out");
      await navigate({ to: "/sign-in" });
      return;
    }
    setFailure(null);
    const next = await reload();
    // Only a gateway that says "signed out" sends a person to sign-in; a failed read keeps "/" behind the retry.
    await navigate({ to: next === null ? "/sign-in" : "/" });
  }

  let content = children;
  if (failure) {
    content = (
      <main className="p-6">
        <ErrorState message={failure.message} onRetry={() => void reload()} />
      </main>
    );
  } else if (status === "loading") {
    content = (
      <main className="p-6">
        <LoadingState label="Loading session" />
      </main>
    );
  } else if (status === "signed-out") {
    content = <SignInPage />;
  }

  return (
    <SessionContext.Provider value={{ status, session, signInRevision, signIn, signOut, reload }}>
      {content}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}
