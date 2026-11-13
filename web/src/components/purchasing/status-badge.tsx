import {
  TriangleExclamationPoint,
  Ban,
  CircleCheck,
  CircleDashed,
  CircleQuestionMark,
  type LucideIcon,
  ShieldCheck,
  UserCheck,
} from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
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
  AUTO_APPROVED: {
    label: "Auto-approved",
    tone: "success",
    icon: ShieldCheck,
    meaning: "Inside the mandate. The agent may place it without a human.",
  },
  NEEDS_APPROVAL: {
    label: "Needs approval",
    tone: "warning",
    icon: UserCheck,
    meaning: "Outside the mandate. A human must approve the exact total before it is placed.",
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
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          data-status={status}
          className={cn(
            "inline-flex w-fit shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            TONE_CLASSES[meta.tone],
            className,
          )}
        >
          <Icon className="size-3" aria-hidden />
          {meta.label}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{meta.meaning}</TooltipContent>
    </Tooltip>
  );
}
