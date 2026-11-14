import { useId } from "react";

import { type Language, useLanguage, useT } from "@/lib/i18n";

const OPTIONS: { value: Language; label: string }[] = [
  { value: "en", label: "EN" },
  { value: "fi", label: "FI" },
];

export function LanguagePicker() {
  const { language, setLanguage } = useLanguage();
  const t = useT();
  const id = useId();
  return (
    <div role="radiogroup" aria-labelledby={id} className="space-y-1.5">
      <span id={id} className="label-caps block">
        {t("Language")}
      </span>
      <div className="grid grid-cols-2 gap-0.5 rounded-md border p-0.5">
        {OPTIONS.map(({ value, label }) => (
          <label
            key={value}
            className="relative flex cursor-pointer items-center justify-center rounded-sm px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent has-checked:bg-accent has-checked:text-accent-foreground has-focus-visible:ring-[3px] has-focus-visible:ring-ring/70"
          >
            <input
              type="radio"
              name={id}
              value={value}
              checked={language === value}
              onChange={() => setLanguage(value)}
              className="sr-only"
            />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}
