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

/** The endpoint the gateway calls for every brand field (docs/contract.md, "Onboarding lookup"). */
export const LOOKUP_ENDPOINT = "POST /v1/brand/retrieve";

const KITCHEN_TYPES: { value: KitchenType; label: string }[] = [
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
  if (!origin) return null;
  let note: ReactNode;
  if (origin.source && current === origin.value) {
    note = (
      <>
        <Sparkles className="size-3.5 shrink-0" aria-hidden />
        <span>
          From your website via {origin.source.provider}{" "}
          <span className="font-mono text-[0.7rem] whitespace-nowrap">{origin.source.endpoint}</span>
        </span>
      </>
    );
  } else if (origin.source || current !== origin.value) {
    note = (
      <>
        <PenLine className="size-3.5 shrink-0" aria-hidden />
        <span>Edited by you</span>
      </>
    );
  } else {
    note = (
      <>
        <CircleHelp className="size-3.5 shrink-0" aria-hidden />
        <span>Unknown: not found on your website. Fill it in or leave it empty.</span>
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
    toast.success("Kitchen profile saved", { testId: "onboarding-saved-toast" });
    onSaved(profile);
  };

  const common = { values, origins, onChange: change };
  return (
    <Card>
      <form onSubmit={submit} noValidate aria-label="Kitchen profile" className="contents">
        <CardHeader>
          <CardTitle>Check your kitchen profile</CardTitle>
          <CardDescription>
            {lookup?.found
              ? `Filled in from ${lookup.domain}. Check every field and change what is wrong. Nothing is saved until you confirm.`
              : "Fill in what you know. Nothing is saved until you confirm."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <Field label="Kitchen name" name="name" invalid={tried && missingName} {...common} />
          {tried && missingName ? (
            <p role="alert" className="text-sm text-destructive">
              The kitchen needs a name.
            </p>
          ) : null}

          <div className="space-y-1.5" data-field="logoUrl">
            <p id={logoId} className="text-sm font-medium">
              Logo
            </p>
            <div className="flex items-center gap-3">
              {safeLogoUrl(values.logoUrl) ? (
                <img
                  src={safeLogoUrl(values.logoUrl) ?? undefined}
                  alt={`${values.name || "Kitchen"} logo`}
                  className="size-14 shrink-0 rounded-lg border object-contain"
                />
              ) : (
                <span className="flex size-14 shrink-0 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground">
                  None
                </span>
              )}
              {values.logoUrl ? (
                <Button type="button" variant="outline" size="sm" onClick={() => change("logoUrl", "")}>
                  Remove logo
                </Button>
              ) : null}
            </div>
            <FieldNote id={`${logoId}-note`} origin={origins?.logoUrl} current={values.logoUrl} />
          </div>

          <div className="space-y-1.5">
            <Field
              label="Brand colours"
              name="colors"
              placeholder="#1f4d3a, #e9d8a6"
              invalid={tried && badColors}
              {...common}
            />
            {colors.length ? (
              <ul aria-label="Colour preview" className="flex flex-wrap gap-2">
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
                Write each colour as # and six hex digits, e.g. #1f4d3a.
              </p>
            ) : null}
          </div>

          <fieldset className="space-y-4">
            <legend className="mb-3 text-sm font-medium">Address</legend>
            <Field label="Street" name="street" {...common} />
            <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
              <Field label="Postal code" name="postalCode" {...common} />
              <Field label="City" name="city" {...common} />
            </div>
            <Field label="Country" name="country" {...common} />
          </fieldset>

          <div className="space-y-1.5" data-field="kitchenType">
            <Label htmlFor={typeId}>Kitchen type</Label>
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
                    {type.label}
                  </SelectItem>
                ))}
                <SelectItem value={UNKNOWN_TYPE}>Unknown</SelectItem>
              </SelectContent>
            </Select>
            {origins?.kitchenType.source && values.kitchenType === origins.kitchenType.value ? (
              <p className="text-xs text-muted-foreground">
                A guess from the industry your website names. Change it if it is wrong.
              </p>
            ) : null}
            <FieldNote id={`${typeId}-note`} origin={origins?.kitchenType} current={values.kitchenType} />
          </div>

          <Field label="Opening hours" name="openingHours" multiline {...common} />
        </CardContent>
        <CardFooter className="mt-6 flex-wrap gap-3">
          <Button type="submit">Confirm and save</Button>
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
function failureMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "INVALID_QUERY" || error.code === "FREE_EMAIL") return error.message;
    if (error.code === "NOT_SERVED") return "Lookup is not available yet. Fill in the form yourself.";
    // The gateway limits paid lookups (429); api/http.ts reports every 429 as RATE_LIMITED.
    if (error.code === "RATE_LIMITED") return "Too many lookups just now. Wait a minute, or fill in the form yourself.";
  }
  return "The lookup did not work this time. Fill in the form yourself, or try again.";
}

function SavedProfile({ profile, onEdit }: { profile: KitchenBrandProfile; onEdit: () => void }) {
  const type = KITCHEN_TYPES.find((option) => option.value === profile.kitchenType)?.label ?? "Unknown";
  const { street, postalCode, city, country } = profile.address;
  const address = [street, [postalCode, city].filter(Boolean).join(" "), country].filter(Boolean).join(", ");
  return (
    <Card aria-label="Saved kitchen profile">
      <CardHeader>
        <CardTitle className="flex items-center gap-3">
          {safeLogoUrl(profile.logoUrl) ? (
            <img
              src={safeLogoUrl(profile.logoUrl) ?? undefined}
              alt={`${profile.name} logo`}
              className="size-10 rounded-lg border object-contain"
            />
          ) : null}
          {profile.name}
        </CardTitle>
        <CardDescription>Saved. The logo now shows beside the app name.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[9rem_1fr]">
          <dt className="text-muted-foreground">Kitchen type</dt>
          <dd>{type}</dd>
          <dt className="text-muted-foreground">Address</dt>
          <dd>{address || "Unknown"}</dd>
          <dt className="text-muted-foreground">Opening hours</dt>
          <dd>{profile.openingHours ?? "Unknown"}</dd>
        </dl>
      </CardContent>
      <CardFooter className="mt-6">
        <Button variant="outline" onClick={onEdit}>
          Start again
        </Button>
      </CardFooter>
    </Card>
  );
}

export function OnboardingPage() {
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
        message: lookup.found ? null : `Context.dev found nothing for ${lookup.domain}. Fill in the form yourself.`,
      });
    } catch (error) {
      setState({ status: "done", lookup: null, message: failureMessage(error) });
    }
    setRound((value) => value + 1);
    setShowSaved(false);
  };

  return (
    <AppShell activeId="onboarding">
      <div className="mx-auto max-w-2xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Set up your kitchen</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            Type your work email or your website. We look up your name, logo, colours and address, and you check them
            before anything is saved.
          </p>
        </header>

        {showSaved && saved ? (
          <SavedProfile profile={saved} onEdit={() => setShowSaved(false)} />
        ) : (
          <>
            <form onSubmit={lookUp} aria-label="Look up your kitchen" className="space-y-2">
              <Label htmlFor={inputId}>Work email or website</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  id={inputId}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="chef@hotelkuusi.fi or hotelkuusi.fi"
                  autoComplete="email"
                  inputMode="email"
                  autoCapitalize="none"
                  spellCheck={false}
                />
                <Button type="submit" disabled={state.status === "looking" || query.trim() === ""}>
                  {state.status === "looking" ? "Looking up..." : "Look up"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Powered by Context.dev <span className="font-mono">{LOOKUP_ENDPOINT}</span>. Our server makes the call;
                your key never reaches the browser.
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
                Fill in the form by hand
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
