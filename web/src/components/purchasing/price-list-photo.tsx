import { Link } from "@tanstack/react-router";
import { Camera } from "lucide-react";
import { useId, useRef, useState } from "react";

import { useApi } from "@/api";
import type { PriceListRead, PriceListReason, PriceListRow } from "@/api/types";
import { ApiError } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatEur } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { auditActorForRole, useRole } from "@/lib/role";
import { downscalePhoto } from "@/lib/shelf-photo";
import { TONE_CLASSES } from "@/lib/tone";
import type { OwnProduct, Supplier } from "@/types";
import { NemotronMark } from "@/components/nemotron-mark";

/** The name people know; the gateway's `model` field is the id (`nemotron-3.5-super-vl`). */
const MODEL_NAME = "Nemotron 3.5 Super VL";

type Translate = ReturnType<typeof useT>;

/** Why a row needs a person, in plain words (docs/contract.md, "Read a supplier's price list"). */
export const REASON_TEXT: Record<PriceListReason, string> = {
  NAME_UNREADABLE: "The name could not be read.",
  PRICE_UNREADABLE: "The price could not be read.",
  PRICE_UNIT_MISSING: "The list does not say what the price is for (a piece, a kg, a box).",
  UNIT_UNKNOWN: "The unit on the list is not one we know.",
  CURRENCY_UNKNOWN: "The list does not show the currency.",
  PACK_UNCLEAR: "The pack size could not be read.",
  VAT_UNKNOWN: "The list does not say whether the prices include VAT.",
};

/** The field names a row can miss, for "Fill in: …". */
export const FIELD_TEXT = {
  name: "name",
  unit: "unit",
  price: "price",
  pack: "pack size",
  measure: "pack measure (kg or l)",
} as const;
type Field = keyof typeof FIELD_TEXT;

/** The gateway's error codes in plain words. */
export function priceListErrorText(problem: unknown, t: Translate): string {
  const code = problem instanceof ApiError ? problem.code : "";
  const status = problem instanceof ApiError ? problem.status : undefined;
  if (code === "PRICE_LIST_BUSY") return t("Another price list is being read for this kitchen. Wait a moment, then try again.");
  if (code === "VISION_NOT_CONFIGURED" || code === "VISION_UNAVAILABLE" || code === "VISION_TIMEOUT") {
    return t("Nemotron is not answering right now. Try again later, or type the products in on the Products page.");
  }
  if (code === "VISION_REPLY_INVALID") {
    return t("Nemotron's answer could not be used. Try again with a sharper photo, or type the products in on the Products page.");
  }
  if (code === "IMAGE_TOO_LARGE") return t("The photo is too large. Take it again from a little further away.");
  if (code === "NOT_AN_IMAGE") return t("This file is not a photo. Choose a JPEG or PNG photo.");
  if (code === "SUPPLIER_HAS_API") {
    return t("This supplier sends its prices through its own system, so a photo of a price list is not needed.");
  }
  if (code === "SUPPLIER_NOT_FOUND") return t("This supplier is no longer in your list. Reload the page.");
  if (code === "SCOPE_REQUIRED" || status === 403) return t("You may not add products for this kitchen. Ask a manager.");
  if (code === "NOT_FOUND" || status === 404) {
    return t("Reading a price list photo is not switched on on this server yet. Type the products in on the Products page.");
  }
  const message = problem instanceof Error ? problem.message : String(problem);
  return t("The photo was not read: {error} Try again, or type the products in on the Products page.", { error: message });
}

/** One row as the person edits it. Every field starts as the draft says; empty stays empty. */
interface RowForm {
  name: string;
  unit: string;
  packSize: string;
  baseUnit: "" | "KG" | "L";
  price: string;
  ticked: boolean;
}

type RowResult = { ok: true; text: string } | { ok: false; text: string };

function formOf(row: PriceListRow): RowForm {
  const numberText = (value: number | null) => (value == null ? "" : String(value));
  return {
    name: row.draft.name ?? "",
    unit: row.draft.unit ?? "",
    packSize: numberText(row.draft.packSize),
    baseUnit: row.draft.baseUnit ?? "",
    price: numberText(row.draft.priceEur),
    // Only a clean new row starts ticked; a price change or a row to check waits for the person.
    ticked: row.status === "READ" && row.match === null,
  };
}

function positive(value: string): number | null {
  const trimmed = value.trim().replace(",", ".");
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** An existing own product the row would change: any match except one at the same price. */
function changes(row: PriceListRow): boolean {
  return row.match !== null && row.match.kind !== "SAME";
}

/** The fields still empty or wrong. A row saves only when this is empty. */
export function missingFields(row: PriceListRow, form: RowForm): Field[] {
  const missing: Field[] = [];
  if (positive(form.price) == null) missing.push("price");
  if (changes(row)) return missing; // a change sets the price only
  if (!form.name.trim()) missing.push("name");
  if (!form.unit.trim()) missing.push("unit");
  const pack = form.packSize.trim();
  if (row.reasons.includes("PACK_UNCLEAR") || pack) {
    if (positive(form.packSize) == null) missing.push("pack");
    const measured = form.baseUnit || ["KG", "L"].includes(form.unit.trim().toUpperCase());
    if (!measured) missing.push("measure");
  }
  return missing;
}

function RowCard({
  index,
  row,
  form,
  result,
  disabled,
  onChange,
}: {
  index: number;
  row: PriceListRow;
  form: RowForm;
  result: RowResult | undefined;
  disabled: boolean;
  onChange: (next: RowForm) => void;
}) {
  const t = useT();
  const id = useId();
  const field = (name: string) => `${id}-${name}`;
  const check = row.status === "PLEASE_CHECK";
  const same = row.match?.kind === "SAME";
  const changing = changes(row);
  const missing = missingFields(row, form);
  const saved = result?.ok === true;
  const title = row.printed.name ?? t("Row {number}", { number: index + 1 });
  const printed = [row.printed.price, row.printed.priceUnit && `/ ${row.printed.priceUnit}`, row.printed.pack]
    .filter(Boolean)
    .join(" ");
  const newPrice = positive(form.price);
  return (
    <li
      role="group"
      aria-label={title}
      data-testid="price-list-row"
      data-check={check ? "true" : "false"}
      className={`space-y-3 rounded-lg border p-3 ${check ? TONE_CLASSES.warning : "bg-card"}`}
    >
      <div className="flex items-start gap-3">
        <Checkbox
          id={field("tick")}
          aria-label={t("Save {name}", { name: title })}
          checked={form.ticked}
          disabled={disabled || same || saved}
          onCheckedChange={(checked) => onChange({ ...form, ticked: checked === true })}
          className="mt-1"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium break-words text-foreground">“{title}”</p>
            {check ? <Badge variant="outline">{t("Please check")}</Badge> : null}
            {same ? <Badge variant="secondary">{t("Already saved")}</Badge> : changing ? (
              <Badge variant="secondary">{t("Price changed")}</Badge>
            ) : (
              <Badge variant="secondary">{t("New")}</Badge>
            )}
          </div>
          {printed ? (
            <p className="text-xs break-words text-muted-foreground">{t("On the list: {text}", { text: printed })}</p>
          ) : null}
          {row.reasons.map((reason) => (
            <p key={reason} className="text-sm font-medium">
              {t(REASON_TEXT[reason])}
            </p>
          ))}
        </div>
      </div>
      {same && row.match ? (
        <p className="text-sm text-muted-foreground">
          {t("Already in your products as {name} at this price. Nothing to save.", { name: row.match.name })}
        </p>
      ) : null}
      {changing && row.match ? (
        <div className="space-y-2">
          <p className="text-sm">{t("Saving changes the price of {name}. Nothing else changes.", { name: row.match.name })}</p>
          <dl className="grid grid-cols-2 gap-3 text-sm tabular-nums">
            <div>
              <dt className="text-xs text-muted-foreground">{t("Price now")}</dt>
              <dd>{row.match.priceEur == null ? t("not set") : formatEur(row.match.priceEur)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("New price")}</dt>
              <dd>{newPrice == null ? t("not set") : formatEur(newPrice)}</dd>
            </div>
          </dl>
          <div className="grid gap-1 sm:max-w-40">
            <Label htmlFor={field("price")}>{t("Price (EUR)")}</Label>
            <Input
              id={field("price")}
              inputMode="decimal"
              value={form.price}
              disabled={disabled || saved}
              onChange={(event) => onChange({ ...form, price: event.target.value })}
            />
          </div>
        </div>
      ) : null}
      {!same && !changing ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <div className="col-span-2 grid gap-1">
            <Label htmlFor={field("name")}>{t("Name")}</Label>
            <Input
              id={field("name")}
              value={form.name}
              disabled={disabled || saved}
              onChange={(event) => onChange({ ...form, name: event.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={field("unit")}>{t("Unit")}</Label>
            <Input
              id={field("unit")}
              value={form.unit}
              placeholder="ST, KG, L"
              disabled={disabled || saved}
              onChange={(event) => onChange({ ...form, unit: event.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={field("pack")}>{t("Pack size")}</Label>
            <div className="flex gap-1">
              <Input
                id={field("pack")}
                inputMode="decimal"
                value={form.packSize}
                disabled={disabled || saved}
                onChange={(event) => onChange({ ...form, packSize: event.target.value })}
              />
              <select
                aria-label={t("Pack measure")}
                value={form.baseUnit}
                disabled={disabled || saved}
                onChange={(event) => onChange({ ...form, baseUnit: event.target.value as RowForm["baseUnit"] })}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">–</option>
                <option value="KG">kg</option>
                <option value="L">l</option>
              </select>
            </div>
          </div>
          <div className="grid gap-1">
            <Label htmlFor={field("price")}>{t("Price (EUR)")}</Label>
            <Input
              id={field("price")}
              inputMode="decimal"
              value={form.price}
              disabled={disabled || saved}
              onChange={(event) => onChange({ ...form, price: event.target.value })}
            />
          </div>
        </div>
      ) : null}
      {!same && !saved && missing.length > 0 ? (
        <p className="text-sm font-medium text-warning">
          {t("Fill in before saving: {fields}.", { fields: missing.map((name) => t(FIELD_TEXT[name])).join(", ") })}
        </p>
      ) : null}
      {result ? (
        <p role={result.ok ? undefined : "alert"} className={`text-sm font-medium ${result.ok ? "text-success" : "text-danger"}`}>
          {result.text}
        </p>
      ) : null}
    </li>
  );
}

function Summary({ read }: { read: PriceListRead }) {
  const t = useT();
  const toCheck = read.rows.filter((row) => row.status === "PLEASE_CHECK").length;
  return (
    <div className="space-y-1 text-sm">
      <p>
        <NemotronMark />
        {read.durationMs == null
          ? t("Read by {model}: {count} rows, {check} to check.", {
              model: MODEL_NAME,
              count: read.rows.length,
              check: toCheck,
            })
          : t("Read by {model} in {seconds} s: {count} rows, {check} to check.", {
              model: MODEL_NAME,
              seconds: (read.durationMs / 1000).toFixed(1),
              count: read.rows.length,
              check: toCheck,
            })}
      </p>
      {read.vat === "INCLUDED" ? <p>{t("The list says the prices include VAT.")}</p> : null}
      {read.vat === "EXCLUDED" ? <p>{t("The list says the prices are without VAT.")}</p> : null}
      {read.vat === null ? <p>{t("The list does not say whether the prices include VAT.")}</p> : null}
      {read.truncated ? <p className="font-medium">{t("The list has more than 40 rows. Only the first 40 were read.")}</p> : null}
      <p className="text-muted-foreground">
        {t("Allergens stay unknown: a price list says nothing safe about them. Add them on the Products page.")}
      </p>
    </div>
  );
}

/**
 * "Add from a photo of the price list" for a manual or CSV supplier (#1174). The person takes or
 * picks a photo; Nemotron 3.5 Super VL reads it into draft rows; the person checks each row and
 * presses save. Each ticked, complete row is saved with the own-product create (a new product)
 * or change (a new price for a matching product) route, one at a time. Nothing is saved before.
 */
export function PriceListPhoto({ supplier }: { supplier: Supplier }) {
  const t = useT();
  const api = useApi();
  const { role } = useRole();
  const actor = auditActorForRole(role);
  const camera = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const latest = useRef(0);
  const [open, setOpen] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [read, setRead] = useState<PriceListRead | null>(null);
  const [forms, setForms] = useState<RowForm[]>([]);
  const [results, setResults] = useState<Record<number, RowResult>>({});
  const [saving, setSaving] = useState(false);

  // A supplier with an API sends its own prices; the gateway refuses it (422 SUPPLIER_HAS_API).
  if (supplier.adapter === "valio_api") return null;

  async function readPhoto(file: File | undefined) {
    if (!file || reading || saving) return;
    const turn = ++latest.current;
    setOpen(true);
    setReading(true);
    setError(null);
    setRead(null);
    setForms([]);
    setResults({});
    try {
      const answer = await api.readPriceListPhoto(supplier.id, await downscalePhoto(file), actor);
      if (turn !== latest.current) return;
      setRead(answer);
      setForms(answer.rows.map(formOf));
    } catch (problem) {
      if (turn === latest.current) setError(priceListErrorText(problem, t));
    } finally {
      if (turn === latest.current) setReading(false);
    }
  }

  async function save() {
    if (!read || saving) return;
    setSaving(true);
    const next: Record<number, RowResult> = { ...results };
    let stored: OwnProduct[] | null = null;
    for (const [index, row] of read.rows.entries()) {
      const form = forms[index];
      if (!form?.ticked || next[index]?.ok || row.match?.kind === "SAME") continue;
      const missing = missingFields(row, form);
      if (missing.length > 0) {
        next[index] = {
          ok: false,
          text: t("Not saved. Fill in: {fields}.", { fields: missing.map((name) => t(FIELD_TEXT[name])).join(", ") }),
        };
        setResults({ ...next });
        continue;
      }
      const price = positive(form.price) as number;
      try {
        if (changes(row) && row.match) {
          stored ??= await api.listOwnProducts();
          const existing = stored.find((product) => product.id === row.match?.productId);
          if (!existing) throw new ApiError("NOT_FOUND", t("{name} is no longer in your products.", { name: row.match.name }));
          await api.saveOwnProduct({ ...existing, priceEur: price, priceSource: "price_list_photo" });
          next[index] = { ok: true, text: t("Saved: the new price of {name}.", { name: existing.name }) };
        } else {
          const packSize = positive(form.packSize);
          const unit = form.unit.trim();
          await api.saveOwnProduct({
            name: form.name.trim(),
            unit,
            packSize,
            baseUnit: packSize == null ? null : form.baseUnit || (unit.toUpperCase() as "KG" | "L"),
            priceEur: price,
            supplierId: supplier.id,
            // A price list says nothing safe about allergens: unknown, never "free from".
            allergens: null,
            priceSource: "price_list_photo",
          });
          next[index] = { ok: true, text: t("Saved as a new product.") };
        }
      } catch (problem) {
        const message = problem instanceof Error ? problem.message : String(problem);
        next[index] = { ok: false, text: t("Not saved: {error}", { error: message }) };
      }
      setResults({ ...next });
    }
    setSaving(false);
  }

  const input = (ref: React.RefObject<HTMLInputElement | null>, label: string, capture: boolean) => (
    <input
      ref={ref}
      type="file"
      accept="image/*"
      // On a phone this opens the back camera; a laptop shows the file dialog.
      capture={capture ? "environment" : undefined}
      className="sr-only"
      tabIndex={-1}
      aria-label={label}
      onChange={(event) => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = ""; // the same photo can be chosen again
        void readPhoto(file);
      }}
    />
  );

  const ticked = read ? read.rows.filter((row, index) => forms[index]?.ticked && !results[index]?.ok && row.match?.kind !== "SAME").length : 0;
  const savedCount = Object.values(results).filter((result) => result.ok).length;

  return (
    <>
      <Button variant="outline" size="sm" disabled={reading || saving} onClick={() => camera.current?.click()}>
        <Camera aria-hidden />
        {t("Add from a photo of the price list")}
      </Button>
      {input(camera, t("Take a photo of the price list of {supplier}", { supplier: supplier.name }), true)}
      {input(picker, t("Choose a photo of the price list of {supplier}", { supplier: supplier.name }), false)}
      <Dialog open={open} onOpenChange={(next) => (saving ? undefined : setOpen(next))}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("Price list of {supplier}", { supplier: supplier.name })}</DialogTitle>
            <DialogDescription>
              {t("Check every row. Only the rows you tick are saved, and only when you press save.")}
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <div role="status" aria-live="polite">
              {reading ? (
                <p className="text-sm"><NemotronMark />{t("{model} is reading the price list. This takes a few seconds.", { model: MODEL_NAME })}</p>
              ) : null}
              {!reading && read ? <Summary read={read} /> : null}
              {savedCount > 0 ? (
                <p className="text-sm">
                  {t("{count} saved. See them on the", { count: savedCount })}{" "}
                  <Link to="/products" className="text-primary underline underline-offset-4">
                    {t("Products page")}
                  </Link>
                  .
                </p>
              ) : null}
            </div>
            {error ? (
              <p role="alert" className={`rounded-md border px-3 py-2 text-sm ${TONE_CLASSES.danger}`}>
                {error}
              </p>
            ) : null}
            {read && read.rows.length === 0 ? <p className="text-sm">{t("No rows were read on this photo.")}</p> : null}
            {read && read.rows.length > 0 ? (
              <ul className="space-y-3" aria-label={t("Rows read from the price list")}>
                {read.rows.map((row, index) => (
                  <RowCard
                    key={index}
                    index={index}
                    row={row}
                    form={forms[index]}
                    result={results[index]}
                    disabled={saving}
                    onChange={(form) => setForms((current) => current.map((item, at) => (at === index ? form : item)))}
                  />
                ))}
              </ul>
            ) : null}
          </DialogBody>
          <DialogFooter>
            {read && read.rows.length > 0 ? (
              <Button disabled={saving || ticked === 0} onClick={() => void save()}>
                {t("Save checked rows")}
              </Button>
            ) : null}
            <Button variant="outline" disabled={reading || saving} onClick={() => picker.current?.click()}>
              {t("Choose another photo")}
            </Button>
            <DialogClose asChild>
              <Button variant="ghost" disabled={saving}>
                {t("Close")}
              </Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
