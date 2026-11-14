import type { Api, NotificationPreferences } from "@/api/types";
import type { AuditEvent } from "@/types";

type NotificationsApi = Pick<Api, "getNotificationPreferences" | "saveNotificationPreferences">;
type AuditRecorder = (event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason">) => void;

export function createNotificationsMock(recordAudit: AuditRecorder): NotificationsApi {
  let preferences: NotificationPreferences = {
    approvalWaiting: true,
    cutoffTwoHours: true,
    recallAlert: true,
    orderConfirmed: true,
  };
  return {
    async getNotificationPreferences() {
      return { ...preferences };
    },
    async saveNotificationPreferences(next, actor) {
      preferences = { ...next };
      recordAudit({ kind: "settings", actor, summary: "Notification preferences updated", reason: "In-app notification choices changed" });
      return { ...preferences };
    },
  };
}
