import { useApi } from "@/api";
import { gatewayRequest } from "@/api/http";
import { formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import { useLanguage, useT } from "@/lib/i18n";

const LABEL_NAMES: Record<string, string> = {
  EU_ORGANIC_FARMING: "Organic (EU)",
  FINNISH_HEART_SYMBOL: "Heart Symbol",
  GOODS_FROM_FINLAND_BLUE_SWAN: "Hyvää Suomesta (Produced in Finland)",
  HYVAA_SUOMESTA: "Hyvää Suomesta (Produced in Finland)",
  "Hyvää Suomesta": "Hyvää Suomesta (Produced in Finland)",
};

export interface LabelCheck {
  product_id: string; producer: string | null; label: string;
  label_verified: true | "not_found" | "unknown";
  source_url: string | null; checked_at: string | null; scope: string; reason: string;
  synthetic?: boolean;
}

export function LabelEvidence({ check, productName }: { check: LabelCheck; productName?: string }) {
  const t = useT();
  const product = check.synthetic
    ? `${t("Synthetic negative control")} · ${t("Test row")}`
    : `${productName ? `${productName} · ` : ""}${t("Product {id}", { id: check.product_id })}`;
  const verified = check.label_verified === true && check.scope === "producer" &&
    typeof check.source_url === "string" && /^https:\/\//.test(check.source_url) && !!check.checked_at;
  const checkedAt = check.checked_at
    ? t("checked {time}", { time: formatDateTime(check.checked_at) })
    : t("not checked");
  return <div className="space-y-1 rounded border p-3 text-sm">
    <p>{product} · {check.producer ?? t("Legal producer unknown")}</p>
    <p className={verified ? "font-semibold text-green-700 dark:text-green-400" : "font-semibold"}>
      {verified ? t("Producer registration verified") : check.label_verified === "not_found" ? t("Producer not found") : t("Verification unknown")}
    </p>
    <p>{t(LABEL_NAMES[check.label] ?? check.label)} · {t("producer scope · individual product certification unverified")}</p>
    {/* The gateway's reason is an English sentence: the known ones have a Finnish entry. */}
    <p>{t(check.reason)} · {checkedAt}</p>
    {check.source_url && /^https:\/\//.test(check.source_url) && <a className="underline" href={check.source_url} target="_blank" rel="noreferrer">{t("Official producer register")}</a>}
  </div>;
}

export function LabelVerificationDemo() {
  const t = useT();
  const api = useApi();
  const { language } = useLanguage();
  const state = useAsync(async () => {
    const result = await gatewayRequest("/api", "/v1/kitchens/demo-kitchen/label-checks") as {
      checks: LabelCheck[]; negative_control: LabelCheck;
    };
    if (!Array.isArray(result?.checks) || !result.negative_control) throw new Error(t("Verification data unavailable"));
    const ids = [...new Set(result.checks.map(check => check.product_id))];
    const products = await api.getProducts(ids).catch(() => []);
    return { ...result, products };
  }, []);
  const unsupported = state.status === "ready"
    ? state.data.checks.filter(check => check.label_verified === "unknown" && check.reason === "Unsupported label register")
    : [];
  const checked = state.status === "ready"
    ? state.data.checks.filter(check => !unsupported.includes(check))
    : [];
  const productNames = state.status === "ready"
    ? new Map(state.data.products.map(product => [product.id, product.names[language] ?? product.names.en]))
    : new Map();
  return <section className="space-y-3" aria-label={t("Label verification")}>
    <h2 className="text-xl font-semibold">{t("Source-backed label checks")}</h2>
    <p>{t("Context.dev extracted the official producer register. These dated checks verify producer registration; they do not certify an individual SKU.")}</p>
    {state.status === "loading" && <p>{t("Loading verification evidence…")}</p>}
    {state.status === "error" && <p role="alert">{t("Verification unknown: {message}", { message: state.error.message })}</p>}
    {state.status === "ready" && <>
      {checked.map(c => <LabelEvidence key={`${c.product_id}-${c.label}`} check={c} productName={productNames.get(c.product_id)} />)}
      {unsupported.length > 0 && <details className="rounded border p-3 text-sm">
        <summary className="cursor-pointer font-medium">
          {t("Not checked: {count} labels with no public register", { count: unsupported.length })}
        </summary>
        <div className="mt-3 space-y-3">
          {unsupported.map(c => <LabelEvidence key={`${c.product_id}-${c.label}`} check={c} productName={productNames.get(c.product_id)} />)}
        </div>
      </details>}
      <LabelEvidence check={state.data.negative_control} />
    </>}
  </section>;
}
