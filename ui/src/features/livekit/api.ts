import { request } from "../../lib/api/client";
import type { Schemas } from "../../lib/api/types";

/** Token vào room LiveKit; route không dùng API key (worker gắn cuộc gọi theo room). */
export async function requestToken(body: Schemas["LiveKitTokenRequest"]) {
  const { data } = await request<Schemas["LiveKitTokenResponse"]>("/livekit/token", {
    method: "POST",
    json: body,
  });
  return data;
}
