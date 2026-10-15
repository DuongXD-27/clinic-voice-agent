import { useSyncExternalStore } from "react";

/**
 * API key đăng nhập console: Bearer key của bot, nhập ở trang /login. Chỉ lưu trong tab hiện tại
 * (`sessionStorage`, plan ui-vite-react §4.6): đóng tab là phải đăng nhập lại.
 * Chuỗi rỗng = đã đăng nhập với bot tắt auth (BOT_API_KEYS rỗng).
 * sessionStorage có thể bị chặn (chế độ riêng tư, iframe): khi đó key chỉ sống trong bộ nhớ.
 */

const STORAGE_KEY = "callbotApiKey";

export interface AuthState {
  /** null = chưa đăng nhập. */
  apiKey: string | null;
  /** Bị đăng xuất vì bot từ chối key (BAD_KEY), không phải người dùng bấm Đăng xuất. */
  rejected: boolean;
}

let state: AuthState = { apiKey: read(), rejected: false };
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function set(next: AuthState) {
  state = next;
  try {
    if (next.apiKey === null) window.sessionStorage.removeItem(STORAGE_KEY);
    else window.sessionStorage.setItem(STORAGE_KEY, next.apiKey);
  } catch {
    // Không lưu được thì thôi: key vẫn dùng được tới khi tải lại trang.
  }
  listeners.forEach((listener) => {
    listener();
  });
}

export function getApiKey(): string | null {
  return state.apiKey;
}

export function login(apiKey: string): void {
  set({ apiKey: apiKey.trim(), rejected: false });
}

export function logout(): void {
  set({ apiKey: null, rejected: false });
}

/** Bot trả BAD_KEY cho key đang lưu (key bị thu hồi / đổi): về trang đăng nhập kèm lý do. */
export function rejectApiKey(): void {
  if (state.apiKey !== null) set({ apiKey: null, rejected: true });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useAuth(): AuthState {
  return useSyncExternalStore(subscribe, () => state);
}
