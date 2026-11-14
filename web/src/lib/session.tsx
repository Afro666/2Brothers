import { useNavigate } from "@tanstack/react-router";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { useApi } from "@/api";
import { SIGNED_OUT_EVENT } from "@/api/http";
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
  reload(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const navigate = useNavigate();
  const initialLoadStarted = useRef(false);
  const [status, setStatus] = useState<SessionContextValue["status"]>("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [signInRevision, setSignInRevision] = useState(0);
  const [failure, setFailure] = useState<Error | null>(null);

  const reload = useCallback(async () => {
    setStatus("loading");
    setFailure(null);
    try {
      const next = await api.getSession();
      setSession(next);
      setStatus(next ? "signed-in" : "signed-out");
    } catch (cause) {
      if (cause instanceof ApiError && (cause.code === "UNAUTHENTICATED" || cause.status === 401)) {
        setSession(null);
        setStatus("signed-out");
      } else {
        setFailure(cause instanceof Error ? cause : new Error(String(cause)));
      }
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
    setSession(next);
    setSignInRevision((revision) => revision + 1);
    setStatus("signed-in");
    await navigate({ to: "/" });
  }

  async function signOut() {
    try {
      await api.signOut();
    } catch {
    }
    setFailure(null);
    setSession(null);
    setStatus("signed-out");
    await navigate({ to: "/sign-in" });
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
