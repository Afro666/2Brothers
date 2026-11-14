import { Factory, Thermometer, Truck } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatPack, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import type { Product } from "@/types";

import { AllergenList, LabelChip } from "./chips";

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
  const altNames = [product.names.fi, product.names.sv].filter(Boolean).join(" · ");
  return (
    <Card className={cn("gap-4", className)}>
      <CardHeader>
        <CardTitle className="leading-snug">{product.names.en}</CardTitle>
        <CardDescription>
          {product.id} · {product.brand} · {formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit)}
          {altNames ? <span className="block">{altNames}</span> : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <section aria-label={t("Allergens")} className="space-y-1">
          <h4 className="text-xs font-medium text-muted-foreground">{t("Allergens")}</h4>
          <AllergenList allergens={product.allergens} />
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
          <Fact icon={Thermometer} label={t("Temperature")} value={product.temperature?.label ?? "unknown"} />
          <Fact
            icon={Factory}
            label={t("CO2 per kg")}
            value={product.co2KgPerKg == null ? "unknown" : `${formatNumber(product.co2KgPerKg)} kg CO2-eq`}
            hint={t("Product-group estimate")}
          />
          <Fact
            icon={Truck}
            label={t("Delivery reliability")}
            value={formatPercent(product.deliveryReliability)}
            hint={t("Delivered vs ordered")}
          />
        </div>
      </CardContent>
    </Card>
  );
}
