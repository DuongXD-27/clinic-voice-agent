import {
  Activity,
  AudioLines,
  BookOpen,
  LayoutDashboard,
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

export const TOOLS: readonly Tool[] = [
  {
    label: "Gọi từng lượt",
    description: "Gõ hoặc ghi âm từng lượt qua HTTP, đúng contract chấm điểm.",
    icon: PhoneCall,
    to: "/call",
  },
  {
    label: "Gọi trực tiếp",
    description: "Nói chuyện liên tục với bot qua WebRTC/LiveKit như một cuộc gọi thật.",
    icon: AudioLines,
    to: "/livekit",
  },
  {
    label: "Observability",
    description: "Độ trễ, lỗi và chất lượng từng lượt, đọc từ trace.",
    icon: Activity,
    to: "/observability",
  },
];

function toolNavItem({ label, icon, to }: Tool): NavItem {
  return { kind: "route", label, icon, to };
}

export const NAV_SECTIONS: readonly NavSection[] = [
  { items: [{ kind: "route", label: "Tổng quan", icon: LayoutDashboard, to: "/" }] },
  { title: "Công cụ", items: TOOLS.map(toolNavItem) },
  {
    title: "Tài liệu",
    items: [{ kind: "link", label: "API (Swagger)", icon: BookOpen, href: "/docs" }],
  },
];
