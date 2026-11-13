import { AlarmClock, CalendarClock, CircleQuestionMark, Clock, Users, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { TONE_CLASSES, type Tone } from "@/lib/tone";
import type { Urgency } from "@/types";

interface UrgencyMeta {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  /** Sort key: lower is more urgent. UNKNOWN sorts with the urgent ones. */
  rank: number;
  meaning: string;
}

export const URGENCY_META: Record<Urgency, UrgencyMeta> = {
  GUESTS_AFFECTED_TODAY: {
    label: "Guests affected today",
    tone: "danger",
    icon: Users,
    rank: 0,
    meaning: "A dish on today's menu cannot be served without this.",
  },
  UNKNOWN: {
    label: "Unknown: treat as urgent",
    tone: "danger",
    icon: CircleQuestionMark,
    rank: 1,
    meaning: "A value the urgency needs is missing. A missing value is never safe.",
  },
  RUNS_OUT_BEFORE_NEXT_DELIVERY: {
    label: "Runs out before next delivery",
    tone: "warning",
    icon: AlarmClock,
    rank: 2,
    meaning: "Stock ends before the next delivery can arrive.",
  },
  DUE_NOW: {
    label: "Due now",
    tone: "info",
    icon: Clock,
    rank: 3,
    meaning: "Stock is at the reorder point. Order in this cycle.",
  },
  CAN_WAIT: {
    label: "Can wait",
    tone: "neutral",
    icon: CalendarClock,
    rank: 4,
    meaning: "Covered until after the next delivery.",
  },
};

export function compareUrgency(a: Urgency, b: Urgency): number {
  return URGENCY_META[a].rank - URGENCY_META[b].rank;
}

export function UrgencyBadge({ urgency, className }: { urgency: Urgency; className?: string }) {
  const meta = URGENCY_META[urgency];
  const Icon = meta.icon;
  return (
    <span
      data-urgency={urgency}
      title={meta.meaning}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE_CLASSES[meta.tone],
        className,
      )}
    >
      <Icon className="size-3" aria-hidden />
      {meta.label}
    </span>
  );
}
