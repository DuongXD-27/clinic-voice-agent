import { DEFAULT_APPOINTMENT, DEFAULT_CALLER, type Direction } from "./config";

export type ScenarioStep =
  { kind: "say"; text: string; expect: string } | { kind: "silence"; expect: string };

export interface Scenario {
  id: string;
  title: string;
  direction: Direction;
  expect: string;
  summary: string;
  steps: readonly ScenarioStep[];
  /** Biến thể thất bại của cùng kịch bản, nếu có. */
  variant?: { title: string; steps: readonly ScenarioStep[] };
  /** Kịch bản phụ thuộc khung giờ trống duy nhất của mock (xem slotOutsideWindow). */
  needsSlotWindow?: boolean;
}

/** Cấu hình điền sẵn cho từng hướng gọi (dữ liệu mẫu của clinic mock). */
export const PRESETS: Readonly<
  Record<Direction, { appointmentId?: string; callerNumber?: string }>
> = {
  outbound: { appointmentId: DEFAULT_APPOINTMENT },
  inbound: { callerNumber: DEFAULT_CALLER },
};

export const SCENARIOS: readonly Scenario[] = [
  {
    id: "confirm",
    title: "Xác nhận lịch",
    direction: "outbound",
    expect: "CONFIRMED",
    summary:
      "Bot gọi bệnh nhân Nguyễn Văn A để nhắc lịch khám Nội tổng quát 15:30 ngày 14/10 tại Vinmec Times City.",
    steps: [
      {
        kind: "say",
        text: "Tôi là Nguyễn Văn A",
        expect: "Bot hỏi ngày tháng năm sinh.",
      },
      {
        kind: "say",
        text: "Ngày 14 tháng 3 năm 1978",
        expect: "Bot đọc lịch và hỏi có đến được không.",
      },
      {
        kind: "say",
        text: "Có, tôi đến được",
        expect: "Bot báo đã xác nhận. Kết thúc với CONFIRMED.",
      },
    ],
  },
  {
    id: "identity",
    title: "Xác minh danh tính",
    direction: "outbound",
    expect: "Xác minh → đọc lịch",
    summary:
      "Bot chỉ nói chi tiết lịch sau khi tên và ngày sinh khớp hồ sơ. Người nghe có thể nói cả hai trong một câu.",
    steps: [
      {
        kind: "say",
        text: "Tôi là Nguyễn Văn A, sinh ngày 14 tháng 3 năm 1978",
        expect: "Xác minh xong ngay lượt 1: bot đọc lịch và hỏi có đến được không.",
      },
      { kind: "say", text: "Có", expect: "Kết thúc với CONFIRMED." },
    ],
    variant: {
      title: "Sai danh tính → TRANSFERRED (IDENTITY_FAILED)",
      steps: [
        { kind: "say", text: "Tôi là Trần Văn B", expect: "Bot hỏi ngày tháng năm sinh." },
        {
          kind: "say",
          text: "Ngày 1 tháng 1 năm 1990",
          expect: "Bot chuyển máy ngay, không nói sai ở đâu. Lịch bị khoá, cần reset.",
        },
      ],
    },
  },
  {
    id: "no-answer",
    title: "Không trả lời",
    direction: "outbound",
    expect: "UNREACHABLE",
    summary:
      "Người nghe máy không nói gì. Bot nhắc lại hai lần rồi kết thúc, không đọc chi tiết lịch.",
    steps: [
      { kind: "silence", expect: "Bot: “Alo, anh chị còn nghe máy không ạ?”" },
      { kind: "silence", expect: "Bot nhắc lại lần hai." },
      { kind: "silence", expect: "Bot xin phép gọi lại sau. Kết thúc với UNREACHABLE (SILENCE)." },
    ],
  },
  {
    id: "booking",
    title: "Đặt lịch",
    direction: "inbound",
    expect: "BOOKED",
    summary: "Bệnh nhân Nguyễn Văn A gọi từ số 0912345600 để đặt lịch khám.",
    needsSlotWindow: true,
    steps: [
      { kind: "say", text: "Tôi là Nguyễn Văn A", expect: "Bot hỏi ngày tháng năm sinh." },
      { kind: "say", text: "14/03/1978", expect: "Bot hỏi anh chị cần hỗ trợ gì." },
      {
        kind: "say",
        text: "Tôi muốn đặt lịch khám",
        expect: "Bot đọc khung 1: 3 giờ chiều ngày 14 tháng 10.",
      },
      { kind: "say", text: "Khung 1", expect: "Bot hỏi chốt khung 3 giờ chiều ngày 14 tháng 10." },
      {
        kind: "say",
        text: "Đúng rồi",
        expect: "Bot báo đã đặt lịch. Kết thúc với BOOKED; người sau cần reset.",
      },
    ],
  },
];

/** Khung trống duy nhất của mock; bot chỉ tìm khung trong 14 ngày tới (SLOT_WINDOW_DAYS). */
const ONLY_SLOT = Date.parse("2026-10-14T15:00:00+07:00");
const SLOT_WINDOW_MS = 14 * 24 * 3600 * 1000;

/** true khi khung trống còn quá xa: bot sẽ chuyển máy (OUT_OF_SCOPE) thay vì đặt được. */
export function slotOutsideWindow(now: number = Date.now()): boolean {
  return ONLY_SLOT - now > SLOT_WINDOW_MS;
}
