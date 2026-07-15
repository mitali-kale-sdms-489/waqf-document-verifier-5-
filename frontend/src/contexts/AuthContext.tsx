import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { AuthUser, Role } from "@/types/auth";
import { isValidAuthUser } from "@/types/auth";
import { apiClient, getStoredToken, setStoredToken } from "@/api/client";
const USER_STORAGE_KEY = "waqf_docverify_user";

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  /** True while rehydrating a session from storage on first load. */
  isLoading: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  register: (fullName: string, email: string, password: string) => Promise<AuthUser>;
  logout: () => void;
  /** True for the full-access account — sees Review, Reports, Admin settings. */
  isElevated: boolean;
  /** True for the upload-only account. */
  isUser: boolean;
  hasAnyRole: (roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);




export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = getStoredToken();
    const storedUser = localStorage.getItem(USER_STORAGE_KEY);
    if (token && storedUser) {
      try {
        const parsed: unknown = JSON.parse(storedUser);
        if (isValidAuthUser(parsed)) {
          setUser(parsed);
        } else {
          // Persisted session doesn't match the current Role shape — e.g. left
          // over from an earlier build with different role names. Drop it
          // rather than letting a bad `role` crash the nav later.
          setStoredToken(null);
          localStorage.removeItem(USER_STORAGE_KEY);
        }
      } catch {
        setStoredToken(null);
        localStorage.removeItem(USER_STORAGE_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  async function login(email: string, password: string): Promise<AuthUser> {
  const response = await apiClient.post("/auth/login", {
    email,
    password,
  });

  const token = response.data.access_token;
  const authUser = response.data.user;

  setStoredToken(token);
  localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(authUser));
  setUser(authUser);

  return authUser;
}

  async function register(
  fullName: string,
  email: string,
  password: string
): Promise<AuthUser> {
  const response = await apiClient.post("/auth/register", {
    full_name: fullName,
    email,
    password,
  });

  const token = response.data.access_token;
  const authUser = response.data.user;

  setStoredToken(token);
  localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(authUser));
  setUser(authUser);

  return authUser;
}

  function logout() {
    setStoredToken(null);
    localStorage.removeItem(USER_STORAGE_KEY);
    setUser(null);
  }

  const value = useMemo<AuthContextValue>(() => {
    const role = user?.role;
    return {
      user,
      isAuthenticated: user !== null,
      isLoading,
      login,
      register,
      logout,
      isElevated: role === "SUPERVISOR",
      isUser: role === "USER",
      hasAnyRole: (roles: Role[]) => role !== undefined && roles.includes(role),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, isLoading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an <AuthProvider>");
  }
  return ctx;
}
