import { ApiError, request } from "../../lib/api/client";

export type Probe =
  { state: "checking" } | { state: "up" } | { state: "down"; code: string | null; message: string };

export interface ServiceSnapshot {
  /** GET /health: process còn sống. */
  health: Probe;
  /** GET /ready: Redis và việc dọn session đang ổn. */
  readiness: Probe;
  checkedAt: Date | null;
}

export async function checkServices(signal?: AbortSignal): Promise<ServiceSnapshot> {
  const [health, readiness] = await Promise.all([
    probe("/health", signal),
    probe("/ready", signal),
  ]);
  return { health, readiness, checkedAt: new Date() };
}

async function probe(path: string, signal?: AbortSignal): Promise<Probe> {
  try {
    await request(path, signal ? { signal } : {});
    return { state: "up" };
  } catch (error) {
    if (error instanceof ApiError) {
      return { state: "down", code: error.code, message: error.message };
    }
    throw error;
  }
}
