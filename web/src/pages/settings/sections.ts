import type { ComponentType } from "react";

import { AccountSection } from "@/pages/settings/account";
import { AppearanceSection } from "@/pages/settings/appearance";
import { DataPrivacySection } from "@/pages/settings/data-privacy";
import { DeveloperSection } from "@/pages/settings/developer";
import { EngineSection } from "@/pages/settings/engine";
import { KitchenSection } from "@/pages/settings/kitchen";
import { NotificationsSection } from "@/pages/settings/notifications";
import { PermissionsSection } from "@/pages/settings/permissions";
import { TeamSection } from "@/pages/settings/team";
import { TokensSection } from "@/pages/settings/tokens";

/**
 * Every settings section, in nav order; `id` is the URL: `/settings/<id>`.
 * This list is the only shared place: to build a section, edit its own file.
 */
export const SETTINGS_SECTIONS: { id: string; label: string; component: ComponentType }[] = [
  { id: "account", label: "Account", component: AccountSection },
  { id: "appearance", label: "Appearance", component: AppearanceSection },
  { id: "kitchen", label: "Kitchen", component: KitchenSection },
  { id: "team", label: "Team", component: TeamSection },
  { id: "permissions", label: "Permissions", component: PermissionsSection },
  { id: "tokens", label: "API & MCP tokens", component: TokensSection },
  { id: "notifications", label: "Notifications", component: NotificationsSection },
  { id: "developer", label: "Developer", component: DeveloperSection },
  { id: "data-privacy", label: "Data & privacy", component: DataPrivacySection },
  { id: "engine", label: "Ordering engine", component: EngineSection },
];

/** Where `/settings` lands on a wide screen: what the Settings link showed before the sections existed. */
export const DEFAULT_SETTINGS_SECTION = "engine";
