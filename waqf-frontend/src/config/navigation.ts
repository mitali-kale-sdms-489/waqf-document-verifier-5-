import type { LucideIcon } from "lucide-react";
import { LayoutDashboard, ScanSearch, BarChart3, ShieldAlert, FileUp } from "lucide-react";
import type { Role } from "@/types/auth";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const ALL_NAV_ITEMS: Record<"dashboard" | "upload" | "review" | "reports" | "admin", NavItem> = {
  dashboard: { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  upload: { to: "/upload", label: "Upload", icon: FileUp },
  review: { to: "/review", label: "Review", icon: ScanSearch },
  reports: { to: "/reports", label: "Reports", icon: BarChart3 },
  admin: { to: "/admin", label: "Admin", icon: ShieldAlert },
};

/** Which tabs each role sees, in order. SUPERVISOR runs the full pipeline
 *  (review, reports, admin) but doesn't upload; USER's only job is uploading
 *  documents. */
export const ROLE_NAV_ITEMS: Record<Role, NavItem[]> = {
  SUPERVISOR: [
    ALL_NAV_ITEMS.dashboard,
    ALL_NAV_ITEMS.review,
    ALL_NAV_ITEMS.reports,
    ALL_NAV_ITEMS.admin,
  ],
  USER: [ALL_NAV_ITEMS.dashboard, ALL_NAV_ITEMS.upload],
};

export const ROLE_LABELS: Record<Role, string> = {
  SUPERVISOR: "Supervisor",
  USER: "User",
};

export const ROLE_BADGE_VARIANT: Record<Role, "roleElevated" | "roleStandard"> = {
  SUPERVISOR: "roleElevated",
  USER: "roleStandard",
};
