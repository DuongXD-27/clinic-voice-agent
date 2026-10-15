import {
  Braces,
  ChartLine,
  House,
  MessagesSquare,
  Mic,
  PhoneCall,
  type LucideIcon,
} from "lucide-react";

import type { NavItem, NavSection } from "../components/layout/Sidebar";

export interface Tool {
  label: string;
  description: string;
  icon: LucideIcon;
  to: string;
}

/**
 * Mỗi công cụ một hình riêng, không lẫn nhau: gọi từng lượt là hội thoại (khung chat), chỉ gọi
 * trực tiếp (realtime) mới dùng hình điện thoại.
 */
export const TOOLS: readonly Tool[] = [
  {
    label: "Gọi từng lượt",
    description: "Gõ hoặc ghi âm từng lượt qua HTTP, đúng contract chấm điểm.",
    icon: MessagesSquare,
    to: "/call",
  },
  {
    label: "Gọi trực tiếp",
    description: "Nói chuyện liên tục với bot qua WebRTC/LiveKit như một cuộc gọi thật.",
    icon: PhoneCall,
    to: "/livekit",
  },
  {
    label: "Thử STT",
    description: "Nói vào microphone, xem chữ từng lượt của GipFormer, Gemini Live, ElevenLabs.",
    icon: Mic,
    to: "/stt",
  },
  {
    label: "Observability",
    description: "Độ trễ, lỗi và chất lượng từng lượt, đọc từ trace.",
    icon: ChartLine,
    to: "/observability",
  },
];

function toolNavItem({ label, icon, to }: Tool): NavItem {
  return { kind: "route", label, icon, to };
}

export const NAV_SECTIONS: readonly NavSection[] = [
  { items: [{ kind: "route", label: "Tổng quan", icon: House, to: "/" }] },
  { title: "Công cụ", items: TOOLS.map(toolNavItem) },
  {
    title: "Tài liệu",
    items: [{ kind: "link", label: "API (Swagger)", icon: Braces, href: "/docs" }],
  },
];
