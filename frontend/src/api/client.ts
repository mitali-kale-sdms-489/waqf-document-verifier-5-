import axios from "axios";

/**
 * Base client for the FastAPI backend (see Implementation Guide, Section 1 & 5).
 * In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.ts).
 * In prod, VITE_API_BASE_URL should point at the deployed backend.
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  timeout: 30_000,
});

const TOKEN_STORAGE_KEY = "waqf_docverify_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null) {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      const wasLoggedIn = getStoredToken() !== null;
      setStoredToken(null);
      localStorage.removeItem("waqf_docverify_user");
      // A silently-cleared token with no visible sign-out left users
      // looking "logged in" while every request quietly 401'd underneath
      // them. Force a real redirect so the app state matches reality.
      if (wasLoggedIn && !window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  }
);
