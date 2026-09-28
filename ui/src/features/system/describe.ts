import type { StatusTone } from "../../components/ui/StatusIndicator";
import type { Probe, ServiceSnapshot } from "./api";

export interface StatusView {
  tone: StatusTone;
  label: string;
  pulse: boolean;
}

/** Một dòng tóm tắt cho sidebar: API sống chưa, session store sẵn sàng chưa. */
export function describeOverall({ health, readiness }: ServiceSnapshot): StatusView {
  if (health.state === "checking" || readiness.state === "checking") {
    return { tone: "neutral", label: "Đang kiểm tra…", pulse: true };
  }
  if (health.state === "down") return { tone: "danger", label: "Mất kết nối API", pulse: false };
  if (readiness.state === "down") {
    return { tone: "warning", label: "Session store lỗi", pulse: false };
  }
  return { tone: "success", label: "Hệ thống hoạt động", pulse: false };
}

export function describeProbe(probe: Probe, upLabel: string): StatusView {
  switch (probe.state) {
    case "checking":
      return { tone: "neutral", label: "Đang kiểm tra…", pulse: true };
    case "up":
      return { tone: "success", label: upLabel, pulse: false };
    case "down":
      return { tone: "danger", label: probe.code ?? probe.message, pulse: false };
  }
}
