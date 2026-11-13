import { Send } from "lucide-react";
import { type FormEvent, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
  onSubmit?: (request: ChefRequest) => void;
}) {
  const [text, setText] = useState(initial?.text ?? "");
  const [covers, setCovers] = useState(initial?.covers == null ? "" : String(initial.covers));
  const [date, setDate] = useState(initial?.deliveryDate ?? "");
  const [sent, setSent] = useState<string | null>(null);
  const textId = useId();
  const coversId = useId();
  const dateId = useId();
  const canSend = text.trim().length > 0 && date !== "";

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    const n = covers === "" ? null : Number(covers);
    const request: ChefRequest = {
      text: text.trim(),
      covers: n != null && Number.isFinite(n) ? n : null,
      deliveryDate: date,
    };
    onSubmit?.(request);
    setSent(request.text);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={textId}>What do you need?</Label>
        <Textarea
          id={textId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="1,000 L lactose-free milk by Monday"
          rows={3}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor={coversId}>Covers</Label>
          <Input
            id={coversId}
            type="number"
            inputMode="numeric"
            min={0}
            value={covers}
            onChange={(e) => setCovers(e.target.value)}
            placeholder="e.g. 180"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={dateId}>Needed by</Label>
          <Input id={dateId} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" className="text-sm text-muted-foreground">
          {sent ? `Sent to the agent: "${sent}"` : null}
        </p>
        <Button type="submit" disabled={!canSend}>
          <Send aria-hidden />
          Ask the agent
        </Button>
      </div>
    </form>
  );
}
