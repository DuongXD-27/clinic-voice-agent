/**
 * Điểm gọi mạng duy nhất của UI. Mọi module `features/<tên>/api.ts` đi qua `request()` nên
 * base URL, API key, đo thời gian và cách đọc lỗi FastAPI chỉ nằm một chỗ.
 */

export type HttpMethod = "GET" | "POST" | "PUT";

export interface RequestOptions {
  method?: HttpMethod;
  /** Gửi dạng JSON (tự đặt Content-Type). Không dùng cùng `body`. */
  json?: unknown;
  /** Gửi nguyên văn, vd. file WAV. Không dùng cùng `json`. */
  body?: BodyInit;
  headers?: Record<string, string>;
  /** Bearer key do người dùng nhập; rỗng thì không gửi header Authorization. */
  apiKey?: string;
  /** Mặc định cùng origin với trang. */
  baseUrl?: string;
  signal?: AbortSignal;
}

export interface ApiResult<T> {
  data: T;
  status: number;
  headers: Headers;
  elapsedMs: number;
}

/** Status 0 = không tới được server (mạng, CORS, bị huỷ). */
export const NETWORK_ERROR = "NETWORK_ERROR";

interface ApiErrorInit {
  status: number;
  code: string | null;
  body: unknown;
  headers: Headers | null;
  elapsedMs: number;
}

export class ApiError extends Error {
  override readonly name = "ApiError";
  readonly status: number;
  /** Mã lỗi của backend (vd. BAD_KEY, CALL_NOT_FOUND) nếu có. */
  readonly code: string | null;
  readonly body: unknown;
  /** Header response (vd. X-Demo-*); null khi không tới được server. */
  readonly headers: Headers | null;
  readonly elapsedMs: number;

  constructor(message: string, init: ApiErrorInit) {
    super(message);
    this.status = init.status;
    this.code = init.code;
    this.body = init.body;
    this.headers = init.headers;
    this.elapsedMs = init.elapsedMs;
  }
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  const { method = "GET", json, body, headers = {}, apiKey, baseUrl, signal } = options;
  const finalHeaders: Record<string, string> = { Accept: "application/json", ...headers };
  if (json !== undefined) finalHeaders["Content-Type"] = "application/json";
  const key = apiKey?.trim();
  if (key) finalHeaders.Authorization = `Bearer ${key}`;

  const init: RequestInit = { method, headers: finalHeaders };
  const payload = json !== undefined ? JSON.stringify(json) : body;
  if (payload !== undefined) init.body = payload;
  if (signal) init.signal = signal;

  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(resolveUrl(path, baseUrl), init);
  } catch (error) {
    // Người gọi chủ động huỷ: trả nguyên lỗi để họ bỏ qua. Không dùng `instanceof DOMException`
    // vì lỗi có thể đến từ realm khác (fetch của Node, iframe) nên instanceof sai.
    if (signal?.aborted) throw error;
    throw new ApiError("Không kết nối được tới server.", {
      status: 0,
      code: NETWORK_ERROR,
      body: null,
      headers: null,
      elapsedMs: Math.round(performance.now() - started),
    });
  }
  const elapsedMs = Math.round(performance.now() - started);
  const data = await readBody(response);

  if (!response.ok) {
    throw new ApiError(errorMessage(response.status, data), {
      status: response.status,
      code: errorCode(data),
      body: data,
      headers: response.headers,
      elapsedMs,
    });
  }
  return { data: data as T, status: response.status, headers: response.headers, elapsedMs };
}

export function resolveUrl(path: string, baseUrl?: string): string {
  const base = baseUrl?.trim() || window.location.origin;
  return new URL(path, base.endsWith("/") ? base : `${base}/`).toString();
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** FastAPI trả lỗi ở `detail`: object `{code, message}`, mảng lỗi validate 422, hoặc chuỗi. */
function detailOf(data: unknown): unknown {
  return isRecord(data) ? data.detail : undefined;
}

function errorCode(data: unknown): string | null {
  const detail = detailOf(data);
  if (isRecord(detail) && typeof detail.code === "string") return detail.code;
  // /ready trả `{status, code}` ở cấp ngoài, không qua HTTPException.
  if (isRecord(data) && typeof data.code === "string") return data.code;
  return null;
}

function errorMessage(status: number, data: unknown): string {
  const detail = detailOf(data);
  if (isRecord(detail) && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail)) {
    const first: unknown = detail[0];
    if (isRecord(first) && typeof first.msg === "string") return first.msg;
  }
  if (typeof detail === "string") return detail;
  return `HTTP ${status}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
