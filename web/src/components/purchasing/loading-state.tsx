import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  const t = useT();
  return (
    <div role="status" aria-label={t(label)} className="space-y-3">
      <Skeleton className="h-5 w-1/3" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-16 w-full" />
    </div>
  );
}
