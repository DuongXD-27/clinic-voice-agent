/** Màu badge theo kết quả cuộc gọi. */
export function outcomeTone(outcome: string | null): "success" | "warning" | "danger" | "info" {
  switch (outcome) {
    case "CONFIRMED":
    case "BOOKED":
    case "RESCHEDULED":
    case "CANCELLED":
      return "success";
    case "TRANSFERRED":
      return "warning";
    case "UNREACHABLE":
      return "danger";
    default:
      return "info";
  }
}
