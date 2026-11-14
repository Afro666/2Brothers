import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  const t = useT();
  return (
    <div role="alert" className="space-y-3 rounded-lg border border-destructive/40 p-4">
      <p className="text-sm">{message}</p>
      <Button variant="outline" onClick={onRetry}>
        {t("Try again")}
      </Button>
    </div>
  );
}
