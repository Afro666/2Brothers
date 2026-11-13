/** Semantic tones on the CSS tokens in `index.css`. Never a raw colour in a component. */
export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  info: "border-info/30 bg-info-surface text-info",
  success: "border-success/30 bg-success-surface text-success",
  warning: "border-warning/40 bg-warning-surface text-warning",
  danger: "border-danger/40 bg-danger-surface text-danger",
};
