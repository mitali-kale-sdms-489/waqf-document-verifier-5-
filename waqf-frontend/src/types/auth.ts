export type Role = "USER" | "SUPERVISOR";

/** Runtime-checkable list of valid roles, e.g. for validating a persisted session. */
export const VALID_ROLES: Role[] = ["USER", "SUPERVISOR"];

export interface AuthUser {
  id: number;
  email: string;
  role: Role;
  full_name: string;
}

/** Type guard used to reject stale/corrupt persisted sessions (e.g. from an
 *  earlier build that used different role names) instead of crashing later
 *  when something like ROLE_NAV_ITEMS[user.role] comes back undefined. */
export function isValidAuthUser(value: unknown): value is AuthUser {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "number" &&
    typeof v.email === "string" &&
    typeof v.full_name === "string" &&
    typeof v.role === "string" &&
    VALID_ROLES.includes(v.role as Role)
  );
}
