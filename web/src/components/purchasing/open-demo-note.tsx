import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";

/**
 * The open demo has no sign-in: everyone shares one demo approver (#1052). Say so, so it reads
 * as a choice. A signed-in account has an email; the open demo's person does not.
 * One line at 390 px: the second sentence shows from the `sm` width up.
 */
export function OpenDemoNote() {
  const t = useT();
  const { session } = useSession();
  if (session?.kind !== "human" || session.email) return null;
  const first = t("Open demo: everyone here is the demo approver.");
  const second = t("Sign-in with roles (approver, chef, viewer) is built and switched off for judging.");
  return (
    <p
      data-testid="open-demo-note"
      title={`${first} ${second}`}
      className="truncate text-xs text-muted-foreground sm:whitespace-normal"
    >
      {first}
      <span className="hidden sm:inline"> {second}</span>
    </p>
  );
}
