import { createContext, useContext, useMemo, useState } from "react";
import { loginStudent } from "../../features/auth/api/loginStudent";
import type { LoginRequest } from "../../shared/types/auth";
import { storage } from "../../shared/lib/storage";

type AuthContextValue = {
  isAuthenticated: boolean;
  accessToken: string | null;
  login: (payload: LoginRequest) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const ACCESS_TOKEN_KEY = "lms_access_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(
    storage.getItem(ACCESS_TOKEN_KEY),
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: Boolean(accessToken),
      accessToken,
      login: async (payload) => {
        const response = await loginStudent(payload);
        storage.setItem(ACCESS_TOKEN_KEY, response.access_token);
        setAccessToken(response.access_token);
      },
      logout: () => {
        storage.removeItem(ACCESS_TOKEN_KEY);
        setAccessToken(null);
      },
    }),
    [accessToken],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }

  return context;
}
