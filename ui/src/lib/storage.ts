/**
 * sessionStorage có thể bị chặn (chế độ riêng tư, iframe) và ném lỗi khi truy cập.
 * Chỉ dùng cho tiện ích của người đang xem (API key trong tab này), không cho dữ liệu cần giữ.
 */

export function readSession(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Chuỗi rỗng thì xoá khóa. */
export function writeSession(key: string, value: string): void {
  try {
    if (value) window.sessionStorage.setItem(key, value);
    else window.sessionStorage.removeItem(key);
  } catch {
    // Không lưu được thì thôi: người dùng nhập lại khi mở tab mới.
  }
}
