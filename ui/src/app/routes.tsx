import type { RouteObject } from "react-router";

import { CallPage } from "../features/call/CallPage";
import { HomePage } from "../pages/home/HomePage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { AppLayout } from "./AppLayout";

/** Tách khỏi router để test dựng được bằng createMemoryRouter. */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "call", element: <CallPage /> },
      {
        path: "livekit",
        // livekit-client nặng (~1 MB chưa nén): tách chunk riêng, chỉ tải khi mở trang này.
        lazy: async () => ({
          Component: (await import("../features/livekit/LiveKitPage")).LiveKitPage,
        }),
      },
      {
        path: "stt",
        // Cùng chunk livekit-client với trang gọi trực tiếp, chỉ tải khi mở trang.
        lazy: async () => ({
          Component: (await import("../features/stt/SttPage")).SttPage,
        }),
      },
      {
        path: "observability",
        lazy: async () => ({
          Component: (await import("../features/observability/pages/ObservabilityLayout"))
            .ObservabilityLayout,
        }),
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import("../features/observability/pages/OverviewPage"))
                .OverviewPage,
            }),
          },
          {
            path: "quality",
            lazy: async () => ({
              Component: (await import("../features/observability/pages/QualityPage")).QualityPage,
            }),
          },
          {
            path: "calls/:callKey",
            lazy: async () => ({
              Component: (await import("../features/observability/pages/CallDetailPage"))
                .CallDetailPage,
            }),
          },
          {
            path: "turns/:traceId",
            lazy: async () => ({
              Component: (await import("../features/observability/pages/TurnDetailPage"))
                .TurnDetailPage,
            }),
          },
        ],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
