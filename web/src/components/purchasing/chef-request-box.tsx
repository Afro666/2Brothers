import { Send } from "lucide-react";
import { type FormEvent, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useT } from "@/lib/i18n";
import type { ChefRequest } from "@/types";

/**
 * The chef says what they need in their own words. Covers and date are
 * separate fields so the engine reads numbers, not the model's guess.
 */
export function ChefRequestBox({
  initial,
  onSubmit,
}: {
  initial?: Partial<ChefRequest>;
  onSubmit?: (request: ChefRequest) => void | Promise<void>;
}) {
  const t = useT();
  const [text, setText] = useState(initial?.text ?? "");
  const [covers, setCovers] = useState(initial?.covers == null ? "" : String(initial.covers));
  const [date, setDate] = useState(initial?.deliveryDate ?? "");
  const [sent, setSent] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textId = useId();
  const coversId = useId();
  const dateId = useId();
  const canSend = text.trim().length > 0 && date !== "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSend || pending) return;
    const n = covers === "" ? null : Number(covers);
    const request: ChefRequest = {
      text: text.trim(),
      covers: n != null && Number.isFinite(n) ? n : null,
      deliveryDate: date,
    };
    setSent(null);
    setError(null);
    let result: void | Promise<void>;
    try {
      result = onSubmit?.(request);
    } catch (failure) {
      setSent(null);
      setError(failure instanceof Error ? failure.message : String(failure));
      return;
    }
    if (result instanceof Promise) {
      setPending(true);
      try {
        await result;
        setSent(request.text);
      } catch (failure) {
        setSent(null);
        setError(failure instanceof Error ? failure.message : String(failure));
      } finally {
        setPending(false);
      }
    } else {
      // A plain callback keeps the old immediate "sent" line.
      setSent(request.text);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={textId} className="label-caps text-[11px] leading-4 font-semibold">{t("What do you need?")}</Label>
        <Textarea
          id={textId}
          className="text-[17px] md:text-[17px]"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("1,000 L lactose-free milk by Monday")}
          rows={3}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor={coversId} className="label-caps text-[11px] leading-4 font-semibold">{t("Covers")}</Label>
          <Input
            id={coversId}
            type="number"
            inputMode="numeric"
            min={0}
            value={covers}
            onChange={(e) => setCovers(e.target.value)}
            placeholder={t("e.g. 180")}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={dateId} className="label-caps text-[11px] leading-4 font-semibold">{t("Needed by")}</Label>
          <Input id={dateId} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
          {sent ? t("Sent to the agent: \"{text}\"", { text: sent }) : null}
        </p>
        <Button type="submit" disabled={!canSend || pending}>
          <Send aria-hidden />
          {pending ? t("Asking…") : t("Ask the agent")}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
