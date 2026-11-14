import {
  TriangleExclamationPoint,
  Ban,
  CircleCheck,
  CircleDashed,
  CircleQuestionMark,
  type LucideIcon,
  UserCheck,
} from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { TONE_CLASSES, type Tone } from "@/lib/tone";
import type { OrderStatus } from "@/types";

interface StatusMeta {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  /** What the state means, shown in the tooltip. */
  meaning: string;
}

export const STATUS_META: Record<OrderStatus, StatusMeta> = {
  NEEDS_APPROVAL: {
    label: "Needs approval",
    tone: "warning",
    icon: UserCheck,
    meaning: "Outside the mandate. A human must approve the exact total before it is placed.",
  },
  IN_PROGRESS: {
    label: "In progress",
    tone: "neutral",
    icon: CircleDashed,
    meaning: "The Buyer is still building this proposal, or an approve is running. It cannot be approved yet.",
  },
  BLOCKED_BY_RECALL: {
    label: "Blocked by recall",
    tone: "danger",
    icon: TriangleExclamationPoint,
    meaning: "A line is recalled. The proposal waits for a replacement and cannot be approved as it is.",
  },
  REFUSED: {
    label: "Refused",
    tone: "danger",
    icon: Ban,
    meaning: "Breaks a hard rule, for example an excluded allergen. It cannot be placed, not even with approval.",
  },
  PLACED: {
    label: "Placed",
    tone: "info",
    icon: CircleCheck,
    meaning: "The gateway placed the order and stored the confirmation.",
  },
  NOT_SENT: {
    label: "Not sent",
    tone: "neutral",
    icon: CircleDashed,
    meaning: "The request never left the gateway. It is safe to try again.",
  },
  UNCONFIRMED: {
    label: "Unconfirmed",
    tone: "danger",
    icon: CircleQuestionMark,
    meaning: "The outcome was never recorded. It may be placed. A human must check before anything else. Never resend.",
  },
  SENT_READ_FAILED: {
    label: "Sent, read failed",
    tone: "warning",
    icon: TriangleExclamationPoint,
    meaning: "The order landed, but reading the answer failed. Re-read the order. Never resend.",
  },
};

/** Order state as a badge; the tooltip (hover or keyboard focus) says what it means. */
export function StatusBadge({ status, className }: { status: OrderStatus; className?: string }) {
  const t = useT();
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          data-status={status}
          className={cn(
            "inline-flex w-fit shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70",
            TONE_CLASSES[meta.tone],
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
