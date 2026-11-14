import { useApi } from "@/api";
import type { Api } from "@/api/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useT } from "@/lib/i18n";

/**
 * A quiet "MongoDB Atlas" mark on what the gateway read from Atlas. `of` is the Api method the
 * data came through: on the mock, or while the gateway does not serve it, nothing is shown, so
 * the mark never claims Atlas for sample figures. `what` says what Atlas did, for the tooltip.
 */
export function AtlasMark({ of, what }: { of: keyof Api; what: string }) {
  const t = useT();
  const { live } = useApi();
  if (!live?.has(of)) return null;
  return <AtlasMarkLabel meaning={t(what)} />;
}

/** The mark itself; the tooltip (hover or keyboard focus, as on StatusBadge) says what Atlas did. */
export function AtlasMarkLabel({ meaning }: { meaning: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className="actor-box shrink-0 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70"
          data-actor="machine"
          data-testid="atlas-mark"
        >
          MongoDB Atlas
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{meaning}</TooltipContent>
    </Tooltip>
  );
}
