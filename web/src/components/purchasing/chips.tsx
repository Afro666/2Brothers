import { CircleQuestionMark, Heart, Leaf, Star, TriangleExclamationPoint } from "lucide-react";

import { cn } from "@/lib/utils";
import { TONE_CLASSES } from "@/lib/tone";
import type { Allergen, ProductLabel } from "@/types";

const CHIP = "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap";

/**
 * CONTAINS is a solid danger chip; MAY CONTAIN is a dashed warning chip.
 * The words are in the chip too, so the difference never rests on colour.
 */
export function AllergenChip({ allergen }: { allergen: Allergen }) {
  const contains = allergen.presence === "CONTAINS";
  return (
    <span
      data-presence={allergen.presence}
      className={cn(CHIP, contains ? TONE_CLASSES.danger : cn(TONE_CLASSES.warning, "border-dashed"))}
    >
      {contains ? <TriangleExclamationPoint className="size-3" aria-hidden /> : null}
      <span className="uppercase">{contains ? "Contains" : "May contain"}</span>
      <span>{allergen.name}</span>
    </span>
  );
}

/** Missing allergen data: unknown, never "allergen-free". Styled as a risk. */
export function AllergenUnknownChip() {
  return (
    <span className={cn(CHIP, TONE_CLASSES.danger, "border-dashed")}>
      <CircleQuestionMark className="size-3" aria-hidden />
      Allergen data missing: unknown
    </span>
  );
}

export function AllergenList({ allergens }: { allergens: Allergen[] | null }) {
  if (allergens == null) return <AllergenUnknownChip />;
  if (allergens.length === 0) return <span className="text-xs text-muted-foreground">No allergens declared</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {allergens.map((a) => (
        <AllergenChip key={`${a.code}-${a.presence}`} allergen={a} />
      ))}
    </div>
  );
}

export const LABEL_META: Record<ProductLabel, { text: string; icon: typeof Leaf }> = {
  EU_ORGANIC_FARMING: { text: "Organic (EU)", icon: Leaf },
  GOODS_FROM_FINLAND_BLUE_SWAN: { text: "Finnish swan", icon: Star },
  FINNISH_HEART_SYMBOL: { text: "Heart symbol", icon: Heart },
};

export function LabelChip({ label }: { label: ProductLabel }) {
  const meta = LABEL_META[label];
  const Icon = meta.icon;
  return (
    <span className={cn(CHIP, TONE_CLASSES.success)}>
      <Icon className="size-3" aria-hidden />
      {meta.text}
    </span>
  );
}
