import "./styles/global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { routes } from "./app/routes";

// BASE_URL = "/ui/" (vite.config.ts); router cần dạng không có "/" cuối.
const router = createBrowserRouter(routes, {
  basename: import.meta.env.BASE_URL.replace(/\/$/, ""),
});

const container = document.getElementById("root");
if (!container) throw new Error("Thiếu phần tử #root trong index.html");

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
