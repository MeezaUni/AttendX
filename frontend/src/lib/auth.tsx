import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCsrf } from "./api";

export type StudentInfo = {
  id: number;
  roll_number: string;
  name: string;
  section: string | null;
  face_status: string;
};

export type User = {
  id: number;
  username: string;
  role: "admin" | "student" | "faculty";
  display_name: string;
  must_change_password: boolean;
  student?: StudentInfo;
  csrf_token?: string;
};

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<User>("/api/auth/me");
      setCsrf(me.csrf_token);
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (window.location.pathname.startsWith("/classroom")) {
      setLoading(false);
      return;
    }
    void refresh();
    const onUnauth = () => setUser(null);
    window.addEventListener("attendx:unauthorized", onUnauth);
    return () => window.removeEventListener("attendx:unauthorized", onUnauth);
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const u = await api.post<User>("/api/auth/login", { username, password });
    setCsrf(u.csrf_token);
    setUser(u);
    return u;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      setCsrf("");
      setUser(null);
    }
  }, []);

  return <Ctx.Provider value={{ user, loading, login, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
