import { ChevronRight, Factory, Thermometer, Truck } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatEur, formatNumber, formatPack, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useLanguage, useT } from "@/lib/i18n";
import type { Product } from "@/types";

import { AllergenList, LabelChip } from "./chips";
import { ProductThumb } from "./product-thumb";
import { ProductLink } from "@/components/purchasing/product-link";

function Fact({ icon: Icon, label, value, hint }: { icon: typeof Truck; label: string; value: string; hint?: string }) {
  const t = useT();
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div>
        <div className="text-xs text-muted-foreground">{t(label)}</div>
        <div className={cn("text-sm", value === "unknown" && "font-medium text-warning")}>
          {value === "unknown" ? t("unknown") : value}
        </div>
        {hint ? <div className="text-xs text-muted-foreground">{t(hint)}</div> : null}
      </div>
    </div>
  );
}

/** One catalog product: names, allergens, labels and the facts a buyer weighs. */
export function ProductCard({ product, className }: { product: Product; className?: string }) {
  const t = useT();
  const { language } = useLanguage();
  const title = (language === "fi" ? product.names.fi : undefined) ?? product.names.en;
  const altNames = [language === "fi" ? product.names.en : product.names.fi, product.names.sv]
    .filter((name) => name && name !== title)
    .join(" · ");
  const allergens = product.allergens?.map((allergen) => ({
    ...allergen,
    name: allergen.name === allergen.code ? t("Other allergen ({code})", { code: allergen.code }) : t(allergen.name),
  })) ?? null;
  const temperature = product.temperature?.label.match(/^(Ambient|Chilled|Frozen)(?:, (.+) to (.+) °C)?$/);
  const temperatureLabel = !product.temperature
    ? "unknown"
    : temperature?.[2] != null
      ? t("{temperature}, {minimum} to {maximum} °C", {
          temperature: t(temperature[1]),
          minimum: temperature[2],
          maximum: temperature[3],
        })
      : t(product.temperature.label);
  return (
    <Card className={cn("gap-3", className)}>
      <CardHeader className="flex flex-row items-start gap-3">
        <ProductThumb en={product.names.en} fi={product.names.fi} brand={product.brand} size="lg" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <CardTitle className="leading-snug break-words">
            <ProductLink productId={product.id}>{title}</ProductLink>
          </CardTitle>
          <CardDescription>
            {product.id} · {product.brand} · {formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit)}
            {altNames ? <span className="block">{altNames}</span> : null}
          </CardDescription>
          <ProductLink productId={product.id} className="inline-flex items-center gap-0.5 text-sm font-medium text-primary">
            {t("Suppliers, VAT and stock")}
            <ChevronRight className="size-4" aria-hidden />
          </ProductLink>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm font-medium">
          {product.priceExVat === undefined
            ? t("Live price and stock come with the offer")
            : product.priceExVat === null
              ? t("price unknown")
              : t("{price} per {unit} ex VAT", { price: formatEur(product.priceExVat), unit: product.salesUnit })}
        </p>
        <section aria-label={t("Allergens")} className="space-y-1">
          <h4 className="text-xs font-medium text-muted-foreground">{t("Allergens")}</h4>
          <AllergenList allergens={allergens} />
        </section>
        {product.labels.length > 0 ? (
          <section aria-label={t("Labels")} className="space-y-1">
            <h4 className="text-xs font-medium text-muted-foreground">{t("Labels")}</h4>
            <div className="flex flex-wrap gap-1">
              {product.labels.map((l) => (
                <LabelChip key={l} label={l} />
              ))}
            </div>
          </section>
        ) : null}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Fact icon={Thermometer} label={t("Temperature")} value={temperatureLabel} />
          <Fact
            icon={Factory}
            label={t("CO2 per kg")}
            value={product.co2KgPerKg == null ? "unknown" : `${formatNumber(product.co2KgPerKg)} kg CO2-eq`}
            hint={t("Product-group estimate")}
          />
          {product.deliveryReliability != null ? (
            <Fact
              icon={Truck}
              label={t("Delivery reliability")}
              value={formatPercent(product.deliveryReliability)}
              hint={t("Delivered vs ordered")}
            />
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
