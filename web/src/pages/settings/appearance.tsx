import { useId } from "react";

import { LanguagePicker } from "@/components/purchasing/language-picker";
import { ThemePicker } from "@/components/purchasing/theme-picker";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ACCENT_HUES, type Appearance, setAppearance, useAppearance } from "@/lib/appearance";
import { formatDate, formatEur } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { SettingsSection } from "@/pages/settings/section";

interface Option<T> {
  value: T;
  label: string;
  /** A colour dot before the label. */
  swatch?: string;
}

const ACCENTS: Option<Appearance["accent"]>[] = (
  [
    ["herb", "Herb green"],
    ["blue", "Blue"],
    ["plum", "Plum"],
    ["clay", "Clay"],
    ["teal", "Teal"],
  ] as const
).map(([value, label]) => ({ value, label, swatch: `oklch(0.6 0.13 ${ACCENT_HUES[value]})` }));
const DENSITIES: Option<Appearance["density"]>[] = [
  { value: "comfortable", label: "Comfortable" },
  { value: "compact", label: "Compact" },
];
const NUMBER_FORMATS: Option<Appearance["numberFormat"]>[] = [
  { value: "comma", label: "1,000.50" },
  { value: "space", label: "1 000,50" },
];
const DATE_FORMATS: Option<Appearance["dateFormat"]>[] = [
  { value: "dmy", label: "14 Nov" },
  { value: "numeric", label: "14.11." },
  { value: "mdy", label: "Nov 14" },
];
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Native radios styled as segments, like the theme picker: the browser gives the arrow keys and the checked state. */
function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
}) {
  const id = useId();
  return (
    <div role="radiogroup" aria-labelledby={id} className="space-y-1.5">
      <span id={id} className="block text-xs leading-none font-medium text-muted-foreground">
        {label}
      </span>
      <div className="flex w-fit max-w-full flex-wrap gap-0.5 rounded-md border p-0.5">
        {options.map((option) => (
          <label
            key={option.value}
            className="flex cursor-pointer items-center gap-1.5 rounded-sm px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-accent has-checked:bg-accent has-checked:text-accent-foreground has-focus-visible:ring-[3px] has-focus-visible:ring-ring/70"
          >
            <input
              type="radio"
              name={id}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.swatch ? (
              <span className="size-3 rounded-full" style={{ background: option.swatch }} aria-hidden />
            ) : null}
            {option.label}
          </label>
        ))}
      </div>
    </div>
  );
}

/** Display choices for this browser. Each applies at once and is remembered (lib/appearance.ts). */
export function AppearanceSection() {
  const t = useT();
  const appearance = useAppearance();
  const weekdays = (appearance.weekStartsMonday ? WEEKDAYS : [WEEKDAYS[6], ...WEEKDAYS.slice(0, 6)]).map((day) =>
    t(day),
  );
  return (
    <SettingsSection
      title="Appearance"
      description="How the app looks and how it writes numbers and dates. Kept in this browser."
    >
      <Card>
        <CardContent className="space-y-5">
          <div className="max-w-xs">
            <ThemePicker />
          </div>
          <Choice
            label="Accent colour"
            value={appearance.accent}
            options={ACCENTS}
            onChange={(accent) => setAppearance({ accent })}
          />
          <Choice
            label="Density"
            value={appearance.density}
            options={DENSITIES}
            onChange={(density) => setAppearance({ density })}
          />
          <div className="max-w-xs">
            <LanguagePicker />
          </div>
          <p className="text-sm text-muted-foreground">{t("More languages will come here.")}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-5">
          <Choice
            label="Number format"
            value={appearance.numberFormat}
            options={NUMBER_FORMATS}
            onChange={(numberFormat) => setAppearance({ numberFormat })}
          />
          <Choice
            label="Date format"
            value={appearance.dateFormat}
            options={DATE_FORMATS}
            onChange={(dateFormat) => setAppearance({ dateFormat })}
          />
          <div className="flex items-center gap-2">
            <Checkbox
              id="week-starts-monday"
              checked={appearance.weekStartsMonday}
              onCheckedChange={(checked) => setAppearance({ weekStartsMonday: checked === true })}
            />
            <Label htmlFor="week-starts-monday">Week starts on Monday</Label>
          </div>
          <p className="text-xs text-muted-foreground">
            Planner and demand weeks are supplier weeks: they always run Monday to Sunday.
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t pt-4 text-sm">
            <dt className="text-muted-foreground">Amount</dt>
            <dd className="tabular-nums">{formatEur(1000.5)}</dd>
            <dt className="text-muted-foreground">Date</dt>
            <dd>{formatDate("2026-11-14")}</dd>
            <dt className="text-muted-foreground">Week</dt>
            <dd>{weekdays.join(" ")}</dd>
          </dl>
        </CardContent>
      </Card>
    </SettingsSection>
  );
}
