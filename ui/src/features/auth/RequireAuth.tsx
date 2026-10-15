import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { useAuth } from "../../lib/auth";

/** Chưa đăng nhập (hoặc bot vừa từ chối key): về /login, đăng nhập xong quay lại đúng trang. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { apiKey } = useAuth();
  const location = useLocation();
  if (apiKey === null) {
    const next = `${location.pathname}${location.search}`;
    const to = next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
    return <Navigate to={to} replace />;
  }
  return children;
}
