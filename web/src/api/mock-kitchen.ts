import { ApiError, type Api, type KitchenProfile } from "@/api/types";
import type { AuditEvent } from "@/types";

type KitchenApi = Pick<Api, "getKitchenProfile" | "saveKitchenProfile" | "listTeamMembers">;
type AuditRecorder = (event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason">) => void;

function validTimezone(value: string): boolean {
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}

export function createKitchenMock(recordAudit: AuditRecorder): KitchenApi {
  let profile: KitchenProfile = {
    name: "Kuu School Kitchen",
    type: "school",
    address: "Koulukatu 12, 00100 Helsinki, Finland",
    timezone: "Europe/Helsinki",
    deliveryAddress: "Kuu School, rear delivery entrance, Koulukatu 14, Helsinki",
  };

  return {
    async getKitchenProfile() {
      return structuredClone(profile);
    },
    async saveKitchenProfile(next, actor) {
      const saved = {
        name: next.name.trim(),
        type: next.type,
        address: next.address.trim(),
        timezone: next.timezone.trim(),
        deliveryAddress: next.deliveryAddress.trim(),
      };
      if (!saved.name) throw new ApiError("INVALID", "Kitchen name is required.");
      if (!saved.address) throw new ApiError("INVALID", "Address is required for local weather and holidays.");
      if (!validTimezone(saved.timezone)) throw new ApiError("INVALID", "Enter a valid IANA timezone.");
      if (!saved.deliveryAddress) throw new ApiError("INVALID", "Delivery address is required.");
      profile = saved;
      recordAudit({
        kind: "settings",
        actor,
        summary: "Kitchen profile updated",
        reason: `${saved.name}; ${saved.type}; ${saved.timezone}`,
      });
      return structuredClone(profile);
    },
    async listTeamMembers() {
      return [
        { id: "demo-buyer", name: "Buyer", email: "buyer@demo.kitchen", role: "approver" },
        { id: "demo-chef", name: "Chef", email: "chef@demo.kitchen", role: "chef" },
        { id: "demo-viewer", name: "Valio planner", email: "planner@demo.valio", role: "viewer" },
      ];
    },
  };
}
