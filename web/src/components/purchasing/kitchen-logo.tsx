import { safeLogoUrl, useKitchenBrand } from "@/lib/kitchen-brand";
import { useT } from "@/lib/i18n";

/** The confirmed kitchen's logo beside the app name; nothing until onboarding is confirmed. */
export function KitchenLogo() {
  const t = useT();
  const brand = useKitchenBrand();
  const logoUrl = safeLogoUrl(brand?.logoUrl);
  if (!brand || !logoUrl) return null;
  return (
    <img
      src={logoUrl}
      alt={t("{name} logo", { name: brand.name })}
      title={brand.name}
      className="size-7 shrink-0 rounded-md border object-contain"
    />
  );
}
