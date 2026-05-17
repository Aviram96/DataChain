"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { getCurrentUser, type UserPublic } from "@/lib/auth-api";
import {
  clearSessionAndRedirect,
  registerSessionExpiredHandler,
} from "@/lib/auth-session";
import {
  clearAccessToken,
  getAccessToken,
  getTokenExpiryMs,
  isTokenExpired,
} from "@/lib/auth-token";

import { useToast } from "./toast-provider";

const SESSION_EXPIRED_MESSAGE =
  "Your session has expired. Please sign in again.";

type AuthContextValue = {
  user: UserPublic | null;
  isLoading: boolean;
  refreshSession: () => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { showToast } = useToast();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const expiryTimerRef = useRef<ReturnType<typeof window.setTimeout>>();

  const clearExpiryTimer = useCallback(() => {
    if (expiryTimerRef.current !== undefined) {
      window.clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = undefined;
    }
  }, []);

  const scheduleExpiryLogout = useCallback(
    (token: string) => {
      clearExpiryTimer();
      const expiryMs = getTokenExpiryMs(token);
      if (expiryMs === null) {
        return;
      }
      const delay = expiryMs - Date.now();
      if (delay <= 0) {
        clearSessionAndRedirect({ message: SESSION_EXPIRED_MESSAGE });
        return;
      }
      expiryTimerRef.current = window.setTimeout(() => {
        clearSessionAndRedirect({ message: SESSION_EXPIRED_MESSAGE });
      }, delay);
    },
    [clearExpiryTimer]
  );

  const refreshSession = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      clearExpiryTimer();
      setUser(null);
      setIsLoading(false);
      return;
    }

    if (isTokenExpired(token)) {
      clearExpiryTimer();
      clearSessionAndRedirect({ message: SESSION_EXPIRED_MESSAGE });
      return;
    }

    setIsLoading(true);
    try {
      scheduleExpiryLogout(token);
      const me = await getCurrentUser();
      setUser(me);
    } finally {
      setIsLoading(false);
    }
  }, [clearExpiryTimer, scheduleExpiryLogout]);

  const logout = useCallback(() => {
    clearExpiryTimer();
    clearAccessToken();
    setUser(null);
    showToast("Signed out.", "success");
    router.push("/login");
  }, [clearExpiryTimer, router, showToast]);

  useEffect(() => {
    registerSessionExpiredHandler((message) => showToast(message, "error"));
    return () => registerSessionExpiredHandler(null);
  }, [showToast]);

  useEffect(() => {
    void refreshSession();
    return clearExpiryTimer;
  }, [refreshSession, clearExpiryTimer]);

  const value = useMemo(
    () => ({ user, isLoading, refreshSession, logout }),
    [user, isLoading, refreshSession, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
