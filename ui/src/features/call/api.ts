import { ApiError, request, type RequestOptions } from "../../lib/api/client";
import { DEMO_DEBUG_HEADER, readDemoDebug, type DemoDebug } from "../../lib/api/demoDebug";
import type { Schemas } from "../../lib/api/types";
import type { Exchange } from "./model/callMachine";

export interface Tracked<T> {
  data: T;
  debug: DemoDebug;
  elapsedMs: number;
  exchange: Exchange;
}

/** Lỗi của một request có kèm request/response để panel debug hiện lại. */
export class CallApiError extends Error {
  override readonly name = "CallApiError";
  readonly status: number;
  readonly code: string | null;
  readonly exchange: Exchange;

  constructor(error: ApiError, exchange: Exchange) {
    super(error.message);
    this.status = error.status;
    this.code = error.code;
    this.exchange = exchange;
  }
}

async function tracked<T>(
  method: "GET" | "POST" | "PUT",
  path: string,
  requestBody: unknown,
  options: RequestOptions,
): Promise<Tracked<T>> {
  try {
    const result = await request<T>(path, { ...options, method });
    return {
      data: result.data,
      debug: readDemoDebug(result.headers),
      elapsedMs: result.elapsedMs,
      exchange: {
        method,
        path,
        request: requestBody,
        status: result.status,
        response: result.data,
      },
    };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    throw new CallApiError(error, {
      method,
      path,
      request: requestBody,
      status: error.status,
      response: error.body,
    });
  }
}

export function startCall(body: Schemas["StartCallRequest"], apiKey: string) {
  return tracked<Schemas["StartCallResponse"]>("POST", "/v1/calls", body, {
    json: body,
    apiKey,
    headers: DEMO_DEBUG_HEADER,
  });
}

export function sendTurn(callId: string, body: Schemas["TurnRequest"], apiKey: string) {
  return tracked<Schemas["TurnResponse"]>(
    "POST",
    `/v1/calls/${encodeURIComponent(callId)}/turn`,
    body,
    { json: body, apiKey, headers: DEMO_DEBUG_HEADER },
  );
}

/** Trình duyệt chỉ có blob: URL; backend cần URL tải được nên upload WAV trước khi gửi lượt. */
export function uploadAudio(callId: string, turn: number, wav: Blob, apiKey: string) {
  return tracked<Schemas["DemoAudioUpload"]>(
    "PUT",
    `/demo-api/audio/${encodeURIComponent(callId)}/${turn}.wav`,
    { content_type: "audio/wav", size_bytes: wav.size },
    { body: wav, apiKey, headers: { "Content-Type": "audio/wav" } },
  );
}

export async function getClinicFixtures(apiKey: string, signal?: AbortSignal) {
  const result = await request<Schemas["ClinicFixtures"]>("/demo-api/clinic-fixtures", {
    apiKey,
    ...(signal ? { signal } : {}),
  });
  return result.data;
}

export function resetClinic(appointmentId: string, apiKey: string) {
  const body = { appointment_id: appointmentId };
  return tracked<Schemas["ClinicResetResponse"]>("POST", "/demo-api/clinic-reset", body, {
    json: body,
    apiKey,
  });
}
