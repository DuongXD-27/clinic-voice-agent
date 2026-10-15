import { ApiError, NETWORK_ERROR, request } from "../../lib/api/client";

export type KeyCheck =
  { ok: true } | { ok: false; reason: "bad_key" | "unreachable"; message: string };

/**
 * Kiểm key như smoke test của CD (docs/reference/http-api.md §Xác thực): `POST /v1/calls` với body
 * rỗng. Auth chạy trước validate nên key đúng (hoặc bot tắt auth) trả 422, key sai trả 401 BAD_KEY;
 * không mở cuộc gọi, không gọi Clinic.
 */
export async function checkApiKey(apiKey: string): Promise<KeyCheck> {
  try {
    await request("/v1/calls", { method: "POST", json: {}, apiKey });
    return { ok: true };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 422) return { ok: true };
    if (error.code === "BAD_KEY") {
      return { ok: false, reason: "bad_key", message: "API key không đúng." };
    }
    // Không có mã lỗi của bot (proxy / gateway trả 502…): bot chưa chạy hoặc không tới được.
    const message =
      error.code === NETWORK_ERROR
        ? "Không kết nối được tới bot."
        : error.code === null
          ? `Không kết nối được tới bot (HTTP ${error.status}).`
          : `Bot trả lỗi khi kiểm tra key: ${error.message}`;
    return { ok: false, reason: "unreachable", message };
  }
}
