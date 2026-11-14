import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

// Name left, figure right: the lines of a slip still being printed, with the total last.
const LINES = ["w-2/5", "w-3/5", "w-1/3"];

export function LoadingState({ label = "Loading" }: { label?: string }) {
  const t = useT();
  return (
    <div role="status" aria-label={t(label)}>
      {LINES.map((width) => (
        <div key={width} className="flex items-center justify-between gap-6 border-b py-3">
          <Skeleton className={`h-4 rounded-sm ${width}`} />
          <Skeleton className="h-4 w-14 rounded-sm" />
        </div>
      ))}
      <div className="flex items-center justify-between gap-6 pt-3">
        <Skeleton className="h-5 w-1/4 rounded-sm" />
        <Skeleton className="h-6 w-24 rounded-sm" />
      </div>
    </div>
  );
}
