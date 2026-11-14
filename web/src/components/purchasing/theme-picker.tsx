import { type LucideIcon, Monitor, Moon, Sun } from "lucide-react";
import { useId } from "react";

import { type ThemeChoice, useTheme } from "@/lib/theme";

const OPTIONS: { value: ThemeChoice; label: string; icon: LucideIcon }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/**
 * Light, dark or follow the device. Native radios styled as segments: the
 * browser gives the arrow keys and the checked state. The icon sits above the
 * label so three segments fit the 224 px sidebar.
 */
export function ThemePicker() {
  const { choice, setChoice } = useTheme();
  const id = useId();
  return (
    <div role="radiogroup" aria-labelledby={id} className="space-y-1.5">
      <span id={id} className="label-caps block">
        Theme
      </span>
      <div className="grid grid-cols-3 gap-0.5 rounded-md border p-0.5">
        {OPTIONS.map(({ value, label, icon: Icon }) => (
          <label
            key={value}
            className="relative flex cursor-pointer flex-col items-center gap-1 rounded-sm px-1 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent has-checked:bg-accent has-checked:text-accent-foreground has-focus-visible:ring-[3px] has-focus-visible:ring-ring/70"
          >
            <input
              type="radio"
              name={id}
              value={value}
              checked={choice === value}
              onChange={() => setChoice(value)}
              className="sr-only"
            />
            <Icon className="size-4" aria-hidden />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}
