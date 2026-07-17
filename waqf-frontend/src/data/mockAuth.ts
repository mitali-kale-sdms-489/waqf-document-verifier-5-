import type { AuthUser } from "@/types/auth";

export const mockUsers = {
  // Full-access account: sees Dashboard, Upload, Review, Reports, and Admin settings.
  supervisor: {
    id: 1,
    email: "supervisor@waqf.gov.in",
    role: "SUPERVISOR",
    full_name: "System Administrator",
  },
  // Upload-only account: submits scans, doesn't review/report/configure.
  user: {
    id: 2,
    email: "user@waqf.gov.in",
    role: "USER",
    full_name: "Mohammed Ali",
  },
} as const satisfies Record<string, AuthUser>;

type MockUserKey = keyof typeof mockUsers;

interface MockCredential {
  password: string;
  userKey: MockUserKey;
}

/** Keyed by lowercase email. */
export const mockCredentials: Record<string, MockCredential> = {
  "supervisor@waqf.gov.in": { password: "Supervisor@Waqf2025", userKey: "supervisor" },
  "user@waqf.gov.in": { password: "User@Waqf2025", userKey: "user" },
};

/** Shown on the login screen so people can try each role without a real backend. */
export const DEMO_CREDENTIALS: { role: string; email: string; password: string }[] = [
  {
    role: "Supervisor",
    email: mockUsers.supervisor.email,
    password: mockCredentials[mockUsers.supervisor.email]!.password,
  },
  { role: "User", email: mockUsers.user.email, password: mockCredentials[mockUsers.user.email]!.password },
];

/**
 * Self-service sign-ups. There's no real backend yet, so newly created
 * accounts are persisted to localStorage instead of the in-memory
 * mockCredentials/mockUsers above (which model the two seeded demo logins).
 * New accounts always get the USER role — SUPERVISOR access is provisioned
 * by an administrator, not self-service.
 */
const REGISTERED_USERS_KEY = "waqf_docverify_registered_users";

interface RegisteredUser {
  password: string;
  user: AuthUser;
}

function readRegisteredUsers(): Record<string, RegisteredUser> {
  try {
    const raw = localStorage.getItem(REGISTERED_USERS_KEY);
    return raw ? (JSON.parse(raw) as Record<string, RegisteredUser>) : {};
  } catch {
    return {};
  }
}

function writeRegisteredUsers(users: Record<string, RegisteredUser>) {
  localStorage.setItem(REGISTERED_USERS_KEY, JSON.stringify(users));
}

export function findRegisteredCredential(email: string): RegisteredUser | undefined {
  return readRegisteredUsers()[email.trim().toLowerCase()];
}

export function registerUser(fullName: string, email: string, password: string): AuthUser {
  const key = email.trim().toLowerCase();
  const users = readRegisteredUsers();

  if (mockCredentials[key] || users[key]) {
    throw new Error("An account with that email already exists.");
  }

  const user: AuthUser = {
    id: 1000 + Object.keys(users).length + 1,
    email: key,
    role: "USER",
    full_name: fullName.trim(),
  };

  users[key] = { password, user };
  writeRegisteredUsers(users);
  return user;
}
