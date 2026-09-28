# Plan — Tái cấu trúc UI bằng Vite + React + TypeScript

**Owner:** *Nguyễn Duy Hưng* · **Trạng thái:** Đã triển khai P0–P4 (25-09-2026) — evidence `docs/evidence/ui-vite-react.md` · **Ngày:** 24-09-2026 · **Nhánh:** `feature/optimize-ui-vite-react`
**Nguồn:** `src/callbot/transports/http/static/` (trang demo HTTP, trang LiveKit), `observability_static/`, `Dockerfile`, `docker-compose.prod.yml`, `.github/workflows/ci.yml`, đo trực tiếp trên EC2 production ngày 24-09-2026

## 1. Mục tiêu và điều kiện hoàn thành

> Gom 3 trang UI rời (HTML + JS thuần) về một app React + TypeScript. Tách logic khỏi DOM để test được bằng unit test, và **không tăng RAM trên server**.

| # | Tiêu chí | Cách chứng minh |
| --- | --- | --- |
| AC-1 | Không có process mới trên server; RAM của container `bot` không tăng quá 10 MiB so với trước deploy | `docker stats` trước/sau, ghi vào evidence |
| AC-2 | Build UI chạy trong Docker multi-stage trên GitHub Actions, không bao giờ build trên EC2 | `Dockerfile`, log CD |
| AC-3 | `/ui/*` do FastAPI phục vụ; deep link (vd. `/ui/call`) F5 vẫn mở được | pytest `test_ui_mount.py` |
| AC-4 | Trang Call console đủ tính năng liệt kê ở §4.1 | Checklist §4.1 + Playwright |
| AC-5 | Logic (state cuộc gọi, audio, gọi API) là hàm thuần, có unit test; component có test với API giả (MSW) | `npm test`, coverage cho `features/**/model` và `lib/**` |
| AC-6 | Type của request/response sinh từ OpenAPI của FastAPI; CI báo đỏ khi backend đổi schema mà UI chưa cập nhật | Job CI `ui` bước `api:check` |
| AC-7 | Trong lúc chuyển đổi, `/demo` và `/observability` cũ vẫn chạy; chỉ bỏ ở pha cuối | Test hiện có vẫn xanh đến P4 |

**Ngoài phạm vi:** đổi API backend, đổi luồng hội thoại, SSR. (Ban đầu gồm cả thay `ScriptProcessorNode` bằng `AudioWorklet`; khi làm đã đưa vào — xem §9.)

## 2. Hiện trạng

### 2.1 Server (đo trên EC2 production, 24-09-2026, lúc không có cuộc gọi)

| | Giá trị |
| --- | --- |
| CPU / RAM | 2 vCPU / 1,9 GiB (cỡ t3.small) |
| RAM còn dùng được | ~490 MiB; swap đang dùng 245 MiB |
| `livekit-worker` | 520 MiB lúc rảnh, tăng khi chạy ASR/VAD |
| `bot` (2 worker uvicorn) | 401 MiB |
| `redis` + `caddy` | ~16 MiB |

RAM là giới hạn chính. `docs/reference/livekit-voice-pipeline-2026-09-24.md` §11 đã ghi lại việc worker xử lý chậm hơn thời gian thực khi máy thiếu RAM. Vì vậy UI không được thêm process thường trực nào.

### 2.2 UI

| Trang | File | Vấn đề |
| --- | --- | --- |
| Call console `/demo/` | `static/index.html` (1157 dòng) | CSS, HTML, ~40 hàm JS trong một file; state nằm trong đối tượng `session` và trong chính DOM (`disabled`, `classList`); không có test |
| LiveKit `/demo/livekit-demo.html` | `static/livekit-demo.html` (305 dòng) | Tải `livekit-client` từ CDN không ghim phiên bản; không có test |
| Observability `/observability/` | `observability_static/*.mjs` | Đã tách module, có `node:test`; phần tốt nhất hiện có |

## 3. Quyết định kỹ thuật

| Chủ đề | Chọn | Lý do |
| --- | --- | --- |
| Framework | **Vite + React + TypeScript** | Build ra file tĩnh (0 RAM trên server); dev proxy có sẵn; Vitest dùng chung config. Next.js static export tắt hết SSR/API routes mà vẫn thêm cấu hình (`basePath`, `trailingSlash`, rewrites chỉ cho dev) |
| Router | React Router, `basename: "/ui"` | 3–4 trang, cần deep link |
| State | `useReducer` + reducer thuần mỗi màn hình | Test không cần DOM; chưa cần Redux/Zustand |
| Gọi API | Hàm `request()` bọc `fetch`, type sinh bằng `openapi-typescript` | Không thêm client runtime; type khớp FastAPI |
| CSS | CSS Modules + `tokens.css` (xanh Vinmec, chế độ sáng/tối theo hệ điều hành) | Không thêm thư viện UI, bundle nhỏ; component không viết mã màu trực tiếp |
| Font, icon | Inter variable tự host (chỉ bộ Latin + tiếng Việt), `lucide-react` | Không gọi CDN/Google Fonts; icon tree-shake |
| Test | Vitest + Testing Library + MSW; Playwright cho E2E | Tầng nào test tầng đó (§6) |
| Lint/format | ESLint (typescript-eslint, react-hooks) + Prettier | Tương đương `ruff check` / `ruff format --check` |
| Package manager | npm, commit `package-lock.json`, CI dùng `npm ci` | Node 22 đã có sẵn trên máy dev |
| Phục vụ file | FastAPI `StaticFiles` mount tại `/ui`, có SPA fallback về `index.html` | Không đổi Caddy/compose; cùng origin nên không cần CORS |

## 4. Thiết kế

### 4.1 Tính năng Call console phải giữ (đối chiếu `static/index.html`)

- [x] Cấu hình: API base URL (mặc định origin), API key (lưu `sessionStorage`), Call ID (sinh `c_demo_<base36>`, kiểm `^[A-Za-z0-9_-]{1,128}$`), direction, mode, appointment/caller, locale, max turns
- [x] Dropdown appointment + số điện thoại từ `GET /demo-api/clinic-fixtures`; có "Nhập số khác…"; nút Tải lại; tự tải lại khi cuộc gọi kết thúc
- [x] Health badge từ `GET /health`
- [x] Bắt đầu cuộc gọi `POST /v1/calls`, khoá cấu hình khi đang gọi; nút Phiên mới
- [x] Gửi turn text (Enter gửi, Shift+Enter xuống dòng), gửi im lặng 2 giây (`silence_ms: 2000`)
- [x] Mode audio: ghi mic → resample 16 kHz → WAV PCM16 → `PUT /demo-api/audio/{call_id}/{turn}.wav` → gửi `audio_url`; preview bản ghi
- [x] Tự phát audio của bot; báo khi trình duyệt chặn autoplay
- [x] Header `X-Demo-Debug: 1`; đọc `X-Demo-Extraction-*`, `X-Demo-Transfer-Reason`, `X-Demo-Error-*` cả trên response lỗi
- [x] Bảng extraction lượt gần nhất (tô sáng span trong câu), panel request/response gần nhất, thời gian HTTP
- [x] Hiển thị State / Turn tiếp theo / Outcome
- [x] Lỗi 401 `BAD_KEY` → thông báo hướng dẫn + focus ô API key
- [x] Reset clinic mock (hộp xác nhận, sau đó tạo phiên mới)
- [x] Hướng dẫn 4 kịch bản mẫu: nút điền cấu hình, nút câu mẫu, nút im lặng; cảnh báo cửa sổ 14 ngày của khung 14/10

### 4.2 Cấu trúc thư mục

```text
callbot-vinmec/
└── ui/
    ├── package.json, package-lock.json, vite.config.ts, tsconfig*.json, eslint.config.js
    ├── index.html, public/favicon.svg
    ├── openapi.json                   # xuất từ FastAPI, commit (§4.5)
    ├── e2e/                           # Playwright (P1)
    └── src/
        ├── main.tsx                   # createBrowserRouter(basename "/ui")
        ├── app/                       # nối app: routes, AppLayout, navigation (dữ liệu menu)
        ├── styles/                    # tokens.css (sáng/tối), fonts.css (Inter tự host), global.css
        ├── components/
        │   ├── ui/                    # Button, Badge, Card, StatusIndicator — chỉ nhận props
        │   └── layout/                # Sidebar, PageHeader
        ├── lib/
        │   ├── api/
        │   │   ├── schema.d.ts        # sinh từ openapi.json, không sửa tay
        │   │   ├── types.ts           # Schemas = components["schemas"]
        │   │   ├── client.ts          # request(): base URL, Bearer, ApiError, đo thời gian
        │   │   └── demoDebug.ts       # parse các header X-Demo-* (P1)
        │   ├── audio/                 # mergeFloat32, resampleLinear, encodeWav, useRecorder (P1)
        │   └── cx.ts
        ├── features/
        │   ├── system/                # /health + /ready: api.ts, describe.ts, ServiceStatusProvider
        │   ├── call/                  # P1: model/callMachine.ts, api.ts, components/, CallPage.tsx
        │   ├── livekit/               # P2
        │   └── observability/         # P3
        ├── pages/                     # home/ (tổng quan), NotFoundPage
        └── test/                      # setup Vitest, MSW server
```

Quy tắc phụ thuộc: `components` chỉ nhận props (state + callback), không gọi `fetch`; chỉ `features/*/api.ts` và `lib/api` được gọi mạng. Quy tắc này thay cho `test_only_central_api_client_contains_observability_request_paths`, kiểm bằng ESLint `no-restricted-globals`/`no-restricted-imports`.

### 4.3 State cuộc gọi

```text
          START                 START_OK                 TURN_SENT
 idle ─────────────▶ starting ─────────────▶ active ───────────────▶ sending
  ▲                     │ START_FAILED         ▲  ▲                    │
  │                     ▼                      │  └──── TURN_OK ───────┤ (ended=false)
  │                   idle (+ notice lỗi)      └────── TURN_FAILED ────┤
  │ RESET                                                              │ TURN_OK (ended=true)
  └──────────────────────────── ended ◀────────────────────────────────┘
```

State gồm: `phase`, `config`, `nextTurn`, `messages[]`, `botState`, `outcome`, `lastExtraction`, `lastExchange`, `notice`. Nút nào bật/tắt được suy ra từ `phase` bằng selector (vd. `canSend(state)`), không lưu riêng. Mọi chuyển trạng thái có unit test, gồm cả các chuyển không hợp lệ (vd. `TURN_SENT` khi `ended`).

### 4.4 Tích hợp backend

**Dockerfile:** thêm stage Node ở đầu và copy kết quả vào **sau** các layer model/dependency, để sửa UI không làm tải lại model:

```dockerfile
FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui ./
RUN npm run build                      # → /ui/dist

FROM python:3.12-slim
# ... giữ nguyên các layer hiện tại ...
COPY --from=ui /ui/dist /app/ui
ENV UI_DIST_DIR=/app/ui
```

**Cấu hình:** thêm khóa `ui_dist_dir` vào `config/http.yaml` (env `UI_DIST_DIR`), mặc định rỗng. Rỗng hoặc thư mục không tồn tại thì không mount `/ui` và ghi 1 dòng log. Chạy uvicorn local mà chưa build UI vẫn được.

**Mount (`main.py`):** `SpaStaticFiles(StaticFiles)` trả `index.html` khi file không tồn tại, **trừ** đường dẫn trong `assets/` (asset thiếu phải trả 404 thật). Mount tại `/ui`, không mount ở `/` vì `/audio` được mount trong lifespan và sẽ bị che.

**Vite:** `base: "/ui/"`; `server.proxy` chuyển `/v1`, `/demo-api`, `/livekit`, `/audio`, `/health`, `/ready`, `/internal` tới `http://localhost:8000`.

**`.dockerignore`:** thêm `ui/node_modules`, `ui/dist`, `ui/coverage`, `ui/playwright-report`, `ui/test-results`.

### 4.5 Hợp đồng API

- `scripts/export_openapi.py`: import `create_app()` (không chạy lifespan nên không cần Redis), ghi `ui/openapi.json` đã sắp xếp khóa.
- `npm run api:types`: `openapi-typescript openapi.json -o src/lib/api/schema.d.ts`.
- CI: job Python chạy `export_openapi.py --check` (đỏ nếu file commit lệch với backend); job `ui` chạy `api:types` rồi `git diff --exit-code`.
- Header `X-Demo-*` không có trong OpenAPI nên có type viết tay trong `demoDebug.ts`, kèm test với chuỗi header thật.

### 4.6 Bảo mật

- API key chỉ do người dùng nhập, lưu `sessionStorage` như hiện tại. Không đưa key vào biến `VITE_*`, vì các biến đó bị nhúng vào bundle công khai.
- `/ui` không yêu cầu auth (giống `/demo` hiện tại); các API phía sau vẫn qua `require_api_key`.
- Không dùng `dangerouslySetInnerHTML`; phần tô sáng span dựng bằng mảng node.

## 5. Các pha

| Pha | Nội dung | Kết quả kiểm được |
| --- | --- | --- |
| **P0 — Setup** | Khung `ui/` (Vite react-ts), ESLint/Prettier/Vitest/MSW, `tokens.css`, router + `HomePage`; `export_openapi.py` + `schema.d.ts`; `lib/api/client.ts` + test; `SpaStaticFiles` + khóa `ui_dist_dir` + pytest; Dockerfile multi-stage; `.dockerignore`; job CI `ui` + thêm `ui/**` vào bộ lọc path; mục README | `npm run check` xanh; `make check` xanh; `docker build` ra image có `/app/ui/index.html`; `GET /ui/` và `GET /ui/call` trả 200 |
| **P1 — Call console** | `lib/audio`, `callMachine`, `features/call/*` theo §4.1; test MSW cho 401/404/409/503; Playwright 2 luồng (outbound CONFIRMED, inbound BOOKED) với `CLINIC_BACKEND=sim` | Checklist §4.1 đủ; job CI `e2e` xanh |
| **P2 — LiveKit** | Chuyển `livekit-demo.html`; cài `livekit-client` từ npm, ghim phiên bản | Kết nối được room trên môi trường deploy |
| **P3 — Observability** | Chuyển 5 view sang React, dùng lại logic đã có test (`format`, `*_state`) dưới dạng TS | Test `node:test` hiện có được thay bằng Vitest tương đương |
| **P4 — Chuyển hẳn** | `/demo/` → 307 `/ui/call`, `/demo/livekit-demo.html` → `/ui/livekit`, `/observability/` → `/ui/observability`; xoá `static/`, `observability_static/`, `tests/frontend/`; sửa test/README/docs | `make check` + `npm run check` xanh; đo RAM sau deploy (AC-1) |

Cả 5 pha ghi chung một evidence `docs/evidence/ui-vite-react.md` và commit một lần khi đã xong hết (chốt 25-09-2026).

## 6. Kiểm thử

| Tầng | Công cụ | Nội dung |
| --- | --- | --- |
| Hàm thuần | Vitest | `callMachine` (mọi chuyển trạng thái), `encodeWav` (header RIFF, clip ±1), `resampleLinear`, `demoDebug` parse, highlight span |
| Component | Vitest + Testing Library + MSW | Luồng start → turn → ended; lỗi 401 `BAD_KEY`, 404 `CALL_NOT_FOUND`, 409, 503; fixtures lỗi thì giữ mặc định |
| Backend phục vụ UI | pytest | `/ui/` 200, deep link 200 trả `index.html`, asset thiếu 404, `/audio` và `/v1` không bị che, không mount khi `ui_dist_dir` rỗng |
| Hợp đồng | CI | `openapi.json` / `schema.d.ts` không lệch |
| E2E | Playwright (Chromium) | uvicorn + Redis service + `CLINIC_BACKEND=sim`; chỉ mode text (mic không tự động được) |

Script: `npm run check` = `lint` + `format:check` + `typecheck` + `test`, tương đương `make check`.

## 7. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
| --- | --- | --- |
| CI chậm thêm (npm ci + build) | Thấp | Cache npm; job `ui` chạy song song với job Python |
| Image to thêm | Thấp | Chỉ thêm `dist/` (ước tính < 1 MB); Node không có trong image cuối |
| Lỗi so với trang cũ khi chuyển | Trung bình | Chạy song song đến P4; checklist §4.1; E2E |
| Chuỗi cung ứng npm | Trung bình | Ít dependency, `npm ci` với lockfile, chỉ Dependabot/`npm audit` ở CI |
| Deep link sai khi F5 | Thấp | SPA fallback + pytest |

## 8. Câu hỏi cần chốt

| # | Câu hỏi | Quyết định (24-09-2026) |
| --- | --- | --- |
| Q-1 | URL mới là `/ui/*`, sau P4 thì `/demo` redirect sang? | Có. Link cũ đã gửi cho mentor/team vẫn dùng được |
| Q-2 | Có chuyển Observability (P3) không, hay giữ bản `.mjs` hiện có? | Chuyển, làm cuối |
| Q-3 | Playwright E2E có chạy trên CI mỗi push không? | Có, chỉ khi đổi `ui/**` hoặc `src/callbot/transports/http/**` |
| Q-4 | Giảm `WEB_CONCURRENCY` xuống 1 để lấy lại RAM? | Làm riêng, ngoài plan này |

## 9. Khác với plan khi triển khai

| Chỗ | Plan | Đã làm | Lý do |
| --- | --- | --- | --- |
| Thu âm | Giữ `ScriptProcessorNode` | `AudioWorklet` (`ui/src/lib/audio/recorder.worklet.js`) | API cũ đã deprecated, lint `no-deprecated` chặn; worklet chạy ngoài luồng UI |
| E2E | outbound CONFIRMED + inbound BOOKED | outbound CONFIRMED + inbound im lặng → TRANSFERRED | BOOKED phụ thuộc ngày (khung 14/10 chỉ nằm trong cửa sổ 14 ngày từ 30/09): test đỏ/xanh theo ngày chạy |
| Q-3 E2E trên CI | Chỉ khi đổi `ui/**` hoặc `transports/http/**` | Mọi lần CI | Hai kịch bản đi xuyên engine hội thoại, sửa engine cũng làm hỏng được |
| Response `/demo-api/*` | Không đổi backend | Thêm response model Pydantic (JSON giữ nguyên) | Để OpenAPI mô tả được và UI sinh type thay vì viết tay |
| LiveKit | Chuyển trang | Thêm transcript qua data channel (`call_bridge.py`, topic `callbot.transcript`) | Yêu cầu trace lời thoại trong lúc gọi |
| `/livekit/token` | — | Chưa cài package `livekit` trả 503 `LIVEKIT_UNAVAILABLE` thay vì 500 | Lỗi gặp khi test local |
| Observability local | — | `docker-compose.yml` thêm volume `traces`, bật API ở local | Không có thư mục trace thì API không đăng ký, trang báo 404 |
| Redirect | `/demo/`, `/demo/livekit-demo.html`, `/observability/` | Thêm `/` → `/ui/` | Mở gốc domain không còn 404 |
