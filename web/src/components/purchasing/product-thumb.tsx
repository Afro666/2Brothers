import { useState } from "react";

import { useBrandLogo } from "@/lib/brand-logos";
import { pictureFor, TINTS } from "@/lib/product-picture";
import { cn } from "@/lib/utils";

const SIZES = { sm: "size-8", md: "size-11", lg: "size-14" } as const;
const ICON_SIZES = { sm: "size-4", md: "size-6", lg: "size-7" } as const;
/** What the logo needs behind it (contract: "Product pictures"). */
const BACKGROUNDS = { light: "bg-white", own: "bg-white", dark: "bg-neutral-900" } as const;

/**
 * A generic picture of the product's kind (a milk carton for milk, a cheese for cheese),
 * read from its names. Decorative: the name next to it says what the product is, so a
 * screen reader skips it. Valio's data has no product photos (lib/product-picture.ts).
 * With `brand`, the brand's logo replaces it when Context.dev knows the brand
 * (lib/brand-logos.ts); without one, or when the image fails, the kind tile stays.
 */
export function ProductThumb({
  en,
  fi,
  brand,
  size = "md",
  className,
}: {
  en?: string | null;
  fi?: string | null;
  brand?: string | null;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const picture = pictureFor(en, fi);
  const Icon = picture.icon;
  const logo = useBrandLogo(brand);
  const [broken, setBroken] = useState<string | null>(null);
  if (logo?.logoUrl && broken !== logo.logoUrl) {
    const url = logo.logoUrl;
    return (
      <span
        aria-hidden
        data-logo={logo.brand}
        title={logo.domain ?? logo.brand}
        className={cn(
          "inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-lg border",
          BACKGROUNDS[logo.background ?? "light"],
          SIZES[size],
          className,
        )}
      >
        <img
          src={url}
          alt={`${logo.brand} logo`}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setBroken(url)}
          className="size-full object-contain p-1"
        />
      </span>
    );
  }
  return (
    <span
      aria-hidden
      data-kind={picture.kind}
      title={picture.kind}
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-lg",
        TINTS[picture.tint],
        SIZES[size],
        className,
      )}
    >
      {/* text-current keeps the tint's colour inside a Select or a Button, whose own rules
          recolour any svg without a text- class. */}
      <Icon className={cn(ICON_SIZES[size], "text-current")} strokeWidth={1.75} aria-hidden />
    </span>
  );
}
