import { CircleHelp, PenLine, Sparkles } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useState } from "react";
import { toast } from "sonner";

import { ApiError, useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { safeLogoUrl, saveKitchenBrand, useKitchenBrand } from "@/lib/kitchen-brand";
import type { FieldSource, KitchenBrandLookup, KitchenBrandProfile, KitchenType, LookedUpField } from "@/types";
import { useT } from "@/lib/i18n";

/** The endpoint the gateway calls for every brand field (docs/contract.md, "Onboarding lookup"). */
export const LOOKUP_ENDPOINT = "POST /v1/brand/retrieve";

export const KITCHEN_TYPES: { value: KitchenType; label: string }[] = [
  { value: "hotel", label: "Hotel" },
  { value: "school", label: "School" },
  { value: "hospital", label: "Hospital" },
  { value: "restaurant", label: "Restaurant" },
];
const UNKNOWN_TYPE = "unknown";
const HEX = /^#[0-9a-f]{6}$/i;

type FieldKey =
  | "name"
  | "logoUrl"
  | "colors"
  | "street"
  | "postalCode"
  | "city"
  | "country"
  | "kitchenType"
  | "openingHours";
type Values = Record<FieldKey, string>;
/** What the lookup said for one field: the text it filled in and where it came from. */
type Origin = { value: string; source: FieldSource | null };

const EMPTY: Values = {
  name: "",
  logoUrl: "",
  colors: "",
  street: "",
  postalCode: "",
  city: "",
  country: "",
  kitchenType: UNKNOWN_TYPE,
  openingHours: "",
};

function text<T>(field: LookedUpField<T>, show: (value: T) => string | null): Origin {
  const value = field.value == null ? null : show(field.value);
  return value ? { value, source: field.source } : { value: "", source: null };
}

/** Each field's pre-filled text and source. An address part the provider left out is unknown on its own. */
function originsOf(lookup: KitchenBrandLookup): Record<FieldKey, Origin> {
  const address = lookup.address;
  const part = (key: "street" | "postalCode" | "city" | "country") => text(address, (value) => value[key]);
  const type = text(lookup.kitchenType, (value) => value);
  return {
    name: text(lookup.name, (value) => value),
    logoUrl: text(lookup.logoUrl, safeLogoUrl),
    colors: text(lookup.colors, (value) => value.filter((color) => HEX.test(color)).join(", ") || null),
    street: part("street"),
    postalCode: part("postalCode"),
    city: part("city"),
    country: part("country"),
    kitchenType: type.source ? type : { value: UNKNOWN_TYPE, source: null },
    openingHours: text(lookup.openingHours, (value) => value),
  };
}

function colorsOf(value: string): string[] {
  return value
    .split(/[\s,]+/)
    .map((color) => color.trim())
    .filter(Boolean);
}

/** Under every field: where the value came from, that the person changed it, or that it is unknown. */
function FieldNote({ id, origin, current }: { id: string; origin: Origin | undefined; current: string }) {
  const t = useT();
  if (!origin) return null;
  let note: ReactNode;
  if (origin.source && current === origin.value) {
    note = (
      <>
        <Sparkles className="size-3.5 shrink-0" aria-hidden />
        <span>
          {t("From your website via {provider} ", { provider: origin.source.provider })}
          <span className="font-mono text-[0.7rem] whitespace-nowrap">{origin.source.endpoint}</span>
        </span>
      </>
    );
  } else if (origin.source || current !== origin.value) {
    note = (
      <>
        <PenLine className="size-3.5 shrink-0" aria-hidden />
        <span>{t("Edited by you")}</span>
      </>
    );
  } else {
    note = (
      <>
        <CircleHelp className="size-3.5 shrink-0" aria-hidden />
        <span>{t("Unknown: not found on your website. Fill it in or leave it empty.")}</span>
      </>
    );
  }
  return (
    <p id={id} data-note className="flex items-start gap-1.5 text-xs text-muted-foreground">
      {note}
    </p>
  );
}

function Field({
  label,
  name,
  values,
  origins,
  onChange,
  multiline = false,
  invalid = false,
  placeholder,
}: {
  label: string;
  name: FieldKey;
  values: Values;
  origins: Record<FieldKey, Origin> | null;
  onChange: (name: FieldKey, value: string) => void;
  multiline?: boolean;
  invalid?: boolean;
  placeholder?: string;
}) {
  const id = useId();
  const props = {
    id,
    value: values[name],
    placeholder,
    "aria-describedby": origins ? `${id}-note` : undefined,
    "aria-invalid": invalid || undefined,
    onChange: (event: { target: { value: string } }) => onChange(name, event.target.value),
  };
  return (
    <div className="space-y-1.5" data-field={name}>
      <Label htmlFor={id}>{label}</Label>
      {multiline ? <Textarea rows={2} {...props} /> : <Input {...props} />}
      <FieldNote id={`${id}-note`} origin={origins?.[name]} current={values[name]} />
    </div>
  );
}

function ProfileForm({
  lookup,
  onSaved,
}: {
  lookup: KitchenBrandLookup | null;
  onSaved: (profile: KitchenBrandProfile) => void;
}) {
  const t = useT();
  const typeId = useId();
  const logoId = useId();
  const [origins] = useState(() => (lookup ? originsOf(lookup) : null));
  const [values, setValues] = useState<Values>(() =>
    origins
      ? (Object.fromEntries(Object.entries(origins).map(([key, origin]) => [key, origin.value])) as Values)
      : EMPTY,
  );
  const [tried, setTried] = useState(false);
  const change = (name: FieldKey, value: string) => setValues((previous) => ({ ...previous, [name]: value }));

  const colors = colorsOf(values.colors);
  const badColors = colors.some((color) => !HEX.test(color));
  const missingName = values.name.trim() === "";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTried(true);
    if (missingName || badColors) return;
    const orNull = (value: string) => value.trim() || null;
    const profile: KitchenBrandProfile = {
      domain: lookup?.domain ?? "",
      name: values.name.trim(),
      logoUrl: safeLogoUrl(values.logoUrl),
      colors,
      address: {
        street: orNull(values.street),
        postalCode: orNull(values.postalCode),
        city: orNull(values.city),
        country: orNull(values.country),
      },
      kitchenType: values.kitchenType === UNKNOWN_TYPE ? null : (values.kitchenType as KitchenType),
      openingHours: orNull(values.openingHours),
    };
    saveKitchenBrand(profile);
    toast.success(t("Kitchen profile saved"), { testId: "onboarding-saved-toast" });
    onSaved(profile);
  };

  const common = { values, origins, onChange: change };
  return (
    <Card>
      <form onSubmit={submit} noValidate aria-label={t("Kitchen profile")} className="contents">
        <CardHeader>
          <CardTitle>{t("Check your kitchen profile")}</CardTitle>
          <CardDescription>
            {lookup?.found
              ? t("Filled in from {domain}. Check every field and change what is wrong. Nothing is saved until you confirm.", { domain: lookup.domain })
              : t("Fill in what you know. Nothing is saved until you confirm.")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <Field label={t("Kitchen name")} name="name" invalid={tried && missingName} {...common} />
          {tried && missingName ? (
            <p role="alert" className="text-sm text-destructive">
              {t("The kitchen needs a name.")}
            </p>
          ) : null}

          <div className="space-y-1.5" data-field="logoUrl">
            <p id={logoId} className="text-sm font-medium">
              {t("Logo")}
            </p>
            <div className="flex items-center gap-3">
              {safeLogoUrl(values.logoUrl) ? (
                <img
                  src={safeLogoUrl(values.logoUrl) ?? undefined}
                  alt={t("{name} logo", { name: values.name || t("Kitchen") })}
                  className="size-14 shrink-0 rounded-lg border object-contain"
                />
              ) : (
                <span className="flex size-14 shrink-0 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground">
                  {t("None")}
                </span>
              )}
              {values.logoUrl ? (
                <Button type="button" variant="outline" size="sm" onClick={() => change("logoUrl", "")}>
                  {t("Remove logo")}
                </Button>
              ) : null}
            </div>
            <FieldNote id={`${logoId}-note`} origin={origins?.logoUrl} current={values.logoUrl} />
          </div>

          <div className="space-y-1.5">
            <Field
              label={t("Brand colours")}
              name="colors"
              placeholder="#1f4d3a, #e9d8a6"
              invalid={tried && badColors}
              {...common}
            />
            {colors.length ? (
              <ul aria-label={t("Colour preview")} className="flex flex-wrap gap-2">
                {colors.map((color, index) => (
                  <li
                    key={`${color}-${index}`}
                    title={color}
                    className="size-7 rounded-md border"
                    style={HEX.test(color) ? { backgroundColor: color } : undefined}
                  />
                ))}
              </ul>
            ) : null}
            {tried && badColors ? (
              <p role="alert" className="text-sm text-destructive">
                {t("Write each colour as # and six hex digits, e.g. #1f4d3a.")}
              </p>
            ) : null}
          </div>

          <fieldset className="space-y-4">
            <legend className="mb-3 text-sm font-medium">{t("Address")}</legend>
            <Field label={t("Street")} name="street" {...common} />
            <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
              <Field label={t("Postal code")} name="postalCode" {...common} />
              <Field label={t("City")} name="city" {...common} />
            </div>
            <Field label={t("Country")} name="country" {...common} />
          </fieldset>

          <div className="space-y-1.5" data-field="kitchenType">
            <Label htmlFor={typeId}>{t("Kitchen type")}</Label>
            <Select value={values.kitchenType} onValueChange={(value) => change("kitchenType", value)}>
              <SelectTrigger
                id={typeId}
                className="w-full sm:max-w-xs"
                aria-describedby={origins ? `${typeId}-note` : undefined}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KITCHEN_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {t(type.label)}
                  </SelectItem>
                ))}
                <SelectItem value={UNKNOWN_TYPE}>{t("Unknown")}</SelectItem>
              </SelectContent>
            </Select>
            {origins?.kitchenType.source && values.kitchenType === origins.kitchenType.value ? (
              <p className="text-xs text-muted-foreground">
                {t("A guess from the industry your website names. Change it if it is wrong.")}
              </p>
            ) : null}
            <FieldNote id={`${typeId}-note`} origin={origins?.kitchenType} current={values.kitchenType} />
          </div>

          <Field label={t("Opening hours")} name="openingHours" multiline {...common} />
        </CardContent>
        <CardFooter className="mt-6 flex-wrap gap-3">
          <Button type="submit">{t("Confirm and save")}</Button>
        </CardFooter>
      </form>
    </Card>
  );
}

type Lookup =
  | { status: "idle" }
  | { status: "looking" }
  | { status: "done"; lookup: KitchenBrandLookup | null; message: string | null };

/** A gateway that does not serve the route yet, or cannot reach Context.dev, leaves a blank form. */
function failureMessage(error: unknown, t: ReturnType<typeof useT>): string {
  if (error instanceof ApiError) {
    if (error.code === "INVALID_QUERY" || error.code === "FREE_EMAIL") return error.message;
    if (error.code === "NOT_SERVED") return t("Lookup is not available yet. Fill in the form yourself.");
    // The gateway limits paid lookups (429); api/http.ts reports every 429 as RATE_LIMITED.
    if (error.code === "RATE_LIMITED") return t("Too many lookups just now. Wait a minute, or fill in the form yourself.");
  }
  return t("The lookup did not work this time. Fill in the form yourself, or try again.");
}

function SavedProfile({ profile, onEdit }: { profile: KitchenBrandProfile; onEdit: () => void }) {
  const t = useT();
  const type = KITCHEN_TYPES.find((option) => option.value === profile.kitchenType)?.label ?? "Unknown";
  const { street, postalCode, city, country } = profile.address;
  const address = [street, [postalCode, city].filter(Boolean).join(" "), country].filter(Boolean).join(", ");
  return (
    <Card aria-label={t("Saved kitchen profile")}>
      <CardHeader>
        <CardTitle className="flex items-center gap-3">
          {safeLogoUrl(profile.logoUrl) ? (
            <img
              src={safeLogoUrl(profile.logoUrl) ?? undefined}
              alt={t("{name} logo", { name: profile.name })}
              className="size-10 rounded-lg border object-contain"
            />
          ) : null}
          {profile.name}
        </CardTitle>
        <CardDescription>{t("Saved. The logo now shows beside the app name.")}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[9rem_1fr]">
          <dt className="text-muted-foreground">{t("Kitchen type")}</dt>
          <dd>{t(type)}</dd>
          <dt className="text-muted-foreground">{t("Address")}</dt>
          <dd>{address || t("Unknown")}</dd>
          <dt className="text-muted-foreground">{t("Opening hours")}</dt>
          <dd>{profile.openingHours ?? t("Unknown")}</dd>
        </dl>
      </CardContent>
      <CardFooter className="mt-6">
        <Button variant="outline" onClick={onEdit}>
          {t("Start again")}
        </Button>
      </CardFooter>
    </Card>
  );
}

export function OnboardingPage() {
  const t = useT();
  const api = useApi();
  const inputId = useId();
  const saved = useKitchenBrand();
  const [query, setQuery] = useState("");
  const [state, setState] = useState<Lookup>({ status: "idle" });
  const [round, setRound] = useState(0);
  const [showSaved, setShowSaved] = useState(false);

  const lookUp = async (event: FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    if (!value) return;
    setState({ status: "looking" });
    try {
      const lookup = await api.lookupKitchenBrand(value.includes("@") ? { email: value } : { website: value });
      setState({
        status: "done",
        lookup,
        message: lookup.found ? null : t("Context.dev found nothing for {domain}. Fill in the form yourself.", { domain: lookup.domain }),
      });
    } catch (error) {
      setState({ status: "done", lookup: null, message: failureMessage(error, t) });
    }
    setRound((value) => value + 1);
    setShowSaved(false);
  };

  return (
    <AppShell activeId="onboarding">
      <div className="mx-auto max-w-2xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Set up your kitchen")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Type your work email or your website. We look up your name, logo, colours and address, and you check them before anything is saved.")}
          </p>
        </header>

        {showSaved && saved ? (
          <SavedProfile profile={saved} onEdit={() => setShowSaved(false)} />
        ) : (
          <>
            <form onSubmit={lookUp} aria-label={t("Look up your kitchen")} className="space-y-2">
              <Label htmlFor={inputId}>{t("Work email or website")}</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  id={inputId}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("chef@hotelkuusi.fi or hotelkuusi.fi")}
                  autoComplete="email"
                  inputMode="email"
                  autoCapitalize="none"
                  spellCheck={false}
                />
                <Button type="submit" disabled={state.status === "looking" || query.trim() === ""}>
                  {state.status === "looking" ? t("Looking up...") : t("Look up")}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                {t("Powered by Context.dev")} <span className="font-mono">{LOOKUP_ENDPOINT}</span>. {t("Our server makes the call; your key never reaches the browser.")}
              </p>
            </form>

            {state.status === "done" && state.message ? (
              <p role="status" className="rounded-lg border p-3 text-sm">
                {state.message}
              </p>
            ) : null}

            {state.status === "idle" ? (
              <Button
                variant="link"
                className="h-auto px-0"
                onClick={() => setState({ status: "done", lookup: null, message: null })}
              >
                {t("Fill in the form by hand")}
              </Button>
            ) : null}

            {state.status === "done" ? (
              <ProfileForm key={round} lookup={state.lookup} onSaved={() => setShowSaved(true)} />
            ) : null}
          </>
        )}
      </div>
    </AppShell>
  );
}
