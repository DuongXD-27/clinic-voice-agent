import "./styles/global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { routes } from "./app/routes";

// UI ở gốc domain (vite.config.ts `base: "/"`), không cần basename.
const router = createBrowserRouter(routes);

const container = document.getElementById("root");
if (!container) throw new Error("Thiếu phần tử #root trong index.html");

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
