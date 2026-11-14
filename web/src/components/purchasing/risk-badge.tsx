import { CircleCheck, CircleQuestionMark, TriangleExclamationPoint, Ban, type LucideIcon } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { TONE_CLASSES, type Tone } from "@/lib/tone";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { ShortageRisk } from "@/types";

interface RiskMeta {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  /** Shown in the tooltip: what the state means for the supplier. */
  meaning: string;
}

export const RISK_META: Record<ShortageRisk, RiskMeta> = {
  SHORT: {
    label: "Short",
    tone: "danger",
    icon: Ban,
    meaning: "Forecast demand is higher than the availability on this day.",
  },
  AT_RISK: {
    label: "At risk",
    tone: "warning",
    icon: TriangleExclamationPoint,
    meaning: "Availability only just covers the forecast. A small change makes it short.",
  },
  COVERED: {
    label: "Covered",
    tone: "success",
    icon: CircleCheck,
    meaning: "Availability covers the forecast demand with a margin.",
  },
  UNKNOWN: {
    label: "Unknown: check stock",
    tone: "warning",
    icon: CircleQuestionMark,
    meaning: "Availability is not measured, so the gap cannot be worked out. Check stock.",
  },
};

/** Shortage risk as a badge; unknown has a dashed border so it never looks measured. */
export function RiskBadge({ risk, className }: { risk: ShortageRisk; className?: string }) {
  const t = useT();
  const meta = RISK_META[risk];
  const Icon = meta.icon;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          data-risk={risk}
          className={cn(
            "inline-flex w-fit shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70",
            TONE_CLASSES[meta.tone],
            risk === "UNKNOWN" && "border-dashed",
            className,
          )}
        >
          <Icon className="size-3" aria-hidden />
          {t(meta.label)}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{t(meta.meaning)}</TooltipContent>
    </Tooltip>
  );
}
