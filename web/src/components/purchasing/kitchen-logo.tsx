import { useKitchenBrand } from "@/lib/kitchen-brand";

/** The confirmed kitchen's logo beside the app name; nothing until onboarding is confirmed. */
export function KitchenLogo() {
  const brand = useKitchenBrand();
  if (!brand?.logoUrl) return null;
  return (
    <img
      src={brand.logoUrl}
      alt={`${brand.name} logo`}
      title={brand.name}
      className="size-7 shrink-0 rounded-md border object-contain"
    />
  );
}
