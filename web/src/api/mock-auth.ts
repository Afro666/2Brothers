import type { Api, Session } from "@/api/types";
import { ApiError } from "@/api/types";

export interface DemoAccount {
  label: string;
  email: string;
  password: string;
}

export const MOCK_DEMO_ACCOUNTS: DemoAccount[] = [
  { label: "Chef", email: "chef@demo.kitchen", password: "demo-kitchen-2026" },
  { label: "Buyer", email: "buyer@demo.kitchen", password: "demo-kitchen-2026" },
  { label: "Valio planner", email: "planner@demo.valio", password: "demo-kitchen-2026" },
];

export function createMockAuth(signedOut = false): Pick<Api, "getSession" | "signIn" | "signOut" | "changePassword"> {
  const accounts = MOCK_DEMO_ACCOUNTS.map((account) => ({
    ...account,
    name: account.label,
    role: account.label === "Chef" ? ("chef" as const) : account.label === "Buyer" ? ("approver" as const) : ("viewer" as const),
  }));
  let currentAccount = signedOut ? null : accounts.find((account) => account.role === "approver")!;
  const session = (): Session | null =>
    currentAccount && {
      kind: "human",
      name: currentAccount.name,
      email: currentAccount.email,
      role: currentAccount.role,
      canApprove: currentAccount.role === "approver",
    };

  return {
    async getSession() {
      return session();
    },
    async signIn(email, password) {
      const account = accounts.find((row) => row.email === email.trim().toLowerCase());
      if (!account || account.password !== password) {
        throw new ApiError("INVALID_LOGIN", "wrong email or password");
      }
      currentAccount = account;
      return session()!;
    },
    async signOut() {
      currentAccount = null;
    },
    async changePassword(current, next) {
      if (!currentAccount) throw new ApiError("UNAUTHENTICATED", "sign in first");
      if (currentAccount.password !== current) {
        throw new ApiError("INVALID_LOGIN", "the current password is wrong");
      }
      if (next.length < 10) {
        throw new ApiError("WEAK_PASSWORD", "the password needs at least 10 characters");
      }
      if (current === next) {
        throw new ApiError("WEAK_PASSWORD", "the new password must differ from the current one");
      }
      currentAccount.password = next;
    },
  };
}
