import { Link, useRouter } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** The look of a product name that opens its page: the text stays the same, underline on hover. */
export const PRODUCT_LINK = "rounded-sm underline-offset-2 hover:underline focus-visible:underline focus-visible:outline-2 focus-visible:outline-ring";

/**
 * A product name or thumb that opens the product's own page (`/catalog/$productId`).
 * Without a product code it is the plain content. Outside a router (a component test, the
 * kit page) it is a plain link with the same address.
 */
export function ProductLink({
  productId,
  children,
  className,
  label,
}: {
  productId: string | null | undefined;
  children: ReactNode;
  className?: string;
  /** The accessible name when the content has no text (a thumb alone). */
  label?: string;
}) {
  const router = useRouter({ warn: false });
  if (!productId) return <>{children}</>;
  const classes = cn(PRODUCT_LINK, className);
  if (!router) {
    return (
      <a href={`/catalog/${encodeURIComponent(productId)}`} className={classes} aria-label={label} data-product-link={productId}>
        {children}
      </a>
    );
  }
  return (
    <Link to="/catalog/$productId" params={{ productId }} className={classes} aria-label={label} data-product-link={productId}>
      {children}
    </Link>
  );
}
