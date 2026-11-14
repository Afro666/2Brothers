import { pictureFor } from "@/lib/product-picture";
import { cn } from "@/lib/utils";

const SIZES = { sm: "size-8 text-lg", md: "size-11 text-2xl", lg: "size-14 text-3xl" } as const;

/**
 * A generic picture of the product's kind (a milk glass for milk, a cheese for cheese),
 * read from its names. Decorative: the name next to it says what the product is, so a
 * screen reader skips it. Valio's data has no product photos (lib/product-picture.ts).
 */
export function ProductThumb({
  en,
  fi,
  size = "md",
  className,
}: {
  en?: string | null;
  fi?: string | null;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const picture = pictureFor(en, fi);
  return (
    <span
      aria-hidden
      data-kind={picture.kind}
      title={picture.kind}
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-lg bg-muted leading-none",
        SIZES[size],
        className,
      )}
    >
      {picture.emoji}
    </span>
  );
}
