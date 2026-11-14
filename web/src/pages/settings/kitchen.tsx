import { type FormEvent, useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";

import { useApi } from "@/api";
import type { KitchenProfile, KitchenProfileType } from "@/api/types";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { SampleData } from "@/components/purchasing/sample-data";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { EU_ALLERGENS } from "@/lib/allergens";
import { useSession } from "@/lib/session";
import { useAsync } from "@/lib/use-async";
import { SettingsSection } from "@/pages/settings/section";
import type { KitchenSettings } from "@/types";

const TYPES: { value: KitchenProfileType; label: string }[] = [
  { value: "restaurant", label: "Restaurant" },
  { value: "school", label: "School" },
  { value: "hospital", label: "Hospital" },
  { value: "hotel", label: "Hotel" },
  { value: "cafe", label: "Cafe" },
];

function validTimezone(value: string): boolean {
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}

export function KitchenSection() {
  const api = useApi();
  const { session } = useSession();
  const canEdit = session?.canApprove === true;
  const canEditProfile = canEdit && (!api.live || api.live.has("saveKitchenProfile"));
  const state = useAsync(
    async () => {
      const [profile, settings] = await Promise.all([api.getKitchenProfile(), api.getKitchenSettings()]);
      return { profile, settings };
    },
    [api],
  );
  const [profile, setProfile] = useState<KitchenProfile | null>(null);
  const [settings, setSettings] = useState<KitchenSettings | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingRules, setSavingRules] = useState(false);

  useEffect(() => {
    if (state.status !== "ready") return;
    setProfile(structuredClone(state.data.profile));
    setSettings(structuredClone(state.data.settings));
  }, [state.status, state.status === "ready" ? state.data : null]);

  function changeProfile<Key extends keyof KitchenProfile>(key: Key, value: KitchenProfile[Key]) {
    setProfile((current) => (current ? { ...current, [key]: value } : current));
    setProfileError(null);
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!profile) return;
    const next = {
      ...profile,
      name: profile.name.trim(),
      address: profile.address.trim(),
      timezone: profile.timezone.trim(),
      deliveryAddress: profile.deliveryAddress.trim(),
    };
    if (!next.name) return setProfileError("Kitchen name is required.");
    if (!next.address) return setProfileError("Address is required for local weather and holidays.");
    if (!validTimezone(next.timezone)) return setProfileError("Enter a valid IANA timezone, for example Europe/Helsinki.");
    if (!next.deliveryAddress) return setProfileError("Delivery address is required.");
    setSavingProfile(true);
    setProfileError(null);
    try {
      const saved = await api.saveKitchenProfile(next, "human");
      setProfile(structuredClone(saved));
      toast.success("Kitchen profile saved");
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavingProfile(false);
    }
  }

  async function saveRules(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setSavingRules(true);
    setRulesError(null);
    try {
      const saved = await api.saveKitchenSettings(settings, "human");
      setSettings(structuredClone(saved));
      toast.success("Allergen rules saved");
    } catch (error) {
      setRulesError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavingRules(false);
    }
  }

  return (
    <SettingsSection
      title="Kitchen"
      description="Identity and location for purchasing, local weather and holidays, plus the allergen rules that always apply."
    >
      {state.status === "loading" ? <LoadingState label="Loading kitchen" /> : null}
      {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
      {state.status === "ready" && (!profile || !settings) ? (
        <EmptyState title="Kitchen settings are unavailable">Try loading this section again.</EmptyState>
      ) : null}
      {state.status === "ready" && profile && settings ? (
        <div className="grid items-start gap-5 xl:grid-cols-2">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle>Kitchen profile</CardTitle>
                <SampleData of="getKitchenProfile" />
              </div>
              <CardDescription>The address supports local weather and holiday signals.</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => void saveProfile(event)} noValidate>
                {profileError ? <p role="alert" className="text-sm text-destructive">{profileError}</p> : null}
                {!canEdit ? <p className="text-sm text-muted-foreground">Only an approver can edit kitchen settings.</p> : null}
                {api.live && !api.live.has("saveKitchenProfile") ? (
                  <p className="text-sm text-muted-foreground">The gateway has no kitchen-profile save route, so this sample profile is read-only.</p>
                ) : null}
                <div className="space-y-2">
                  <Label htmlFor="kitchen-name">Kitchen name</Label>
                  <Input id="kitchen-name" value={profile.name} disabled={!canEditProfile || savingProfile} onChange={(event) => changeProfile("name", event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="kitchen-type">Kitchen type</Label>
                  <Select value={profile.type} disabled={!canEditProfile || savingProfile} onValueChange={(value) => changeProfile("type", value as KitchenProfileType)}>
                    <SelectTrigger id="kitchen-type" className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {TYPES.map((type) => <SelectItem key={type.value} value={type.value}>{type.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="kitchen-address">Address</Label>
                  <Textarea id="kitchen-address" value={profile.address} disabled={!canEditProfile || savingProfile} onChange={(event) => changeProfile("address", event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="kitchen-timezone">Timezone</Label>
                  <Input id="kitchen-timezone" value={profile.timezone} disabled={!canEditProfile || savingProfile} onChange={(event) => changeProfile("timezone", event.target.value)} />
                  <p className="text-xs text-muted-foreground">Use an IANA timezone such as Europe/Helsinki.</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="delivery-address">Delivery address</Label>
                  <Textarea id="delivery-address" value={profile.deliveryAddress} disabled={!canEditProfile || savingProfile} onChange={(event) => changeProfile("deliveryAddress", event.target.value)} />
                </div>
                {canEditProfile ? <Button type="submit" disabled={savingProfile}>{savingProfile ? "Saving…" : "Save profile"}</Button> : null}
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Hard allergen rules</CardTitle>
              <CardDescription>Products that contain or may contain a selected allergen are always refused. For example, select gluten cereals for coeliac pupils.</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => void saveRules(event)}>
                {rulesError ? <p role="alert" className="text-sm text-destructive">{rulesError}</p> : null}
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                  {EU_ALLERGENS.map(({ code, name }) => (
                    <div key={code} className="flex items-center gap-2">
                      <Checkbox
                        id={`kitchen-allergen-${code}`}
                        checked={settings.excludedAllergens.includes(code)}
                        disabled={!canEdit || savingRules}
                        onCheckedChange={(checked) => {
                          setSettings((current) => current ? {
                            ...current,
                            excludedAllergens: checked === true
                              ? [...new Set([...current.excludedAllergens, code])]
                              : current.excludedAllergens.filter((item) => item !== code),
                          } : current);
                          setRulesError(null);
                        }}
                      />
                      <Label htmlFor={`kitchen-allergen-${code}`} className="font-normal">{name} ({code})</Label>
                    </div>
                  ))}
                </div>
                <p className="text-sm text-muted-foreground">These are the same rules used by the <Link to="/settings/$section" params={{ section: "engine" }} className="underline underline-offset-4">ordering engine settings</Link>.</p>
                {canEdit ? <Button type="submit" disabled={savingRules}>{savingRules ? "Saving…" : "Save allergen rules"}</Button> : null}
              </form>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </SettingsSection>
  );
}
