# Evidence: Tái cấu trúc UI bằng Vite + React + TypeScript (P0–P4)

## Mục tiêu

Gom ba trang UI rời (HTML + JS thuần: `/demo/`, `/demo/livekit-demo.html`, `/observability/`) về một app
Vite + React + TypeScript trong `ui/`, có design system chung, logic tách khỏi DOM để test được, và
**không thêm process hay RAM trên server** (EC2 2 vCPU / 1,9 GiB, còn ~490 MiB trống lúc đo 24-09-2026).
Plan và các quyết định: [docs/plans/ui-vite-react.md](../plans/ui-vite-react.md) (§9 ghi các chỗ khác plan).

| Pha | Kết quả |
| --- | --- |
| P0 | Khung `ui/`, design token sáng/tối, font Inter tự host, FastAPI phục vụ `/ui` (SPA fallback, cache header), hợp đồng type OpenAPI, Docker multi-stage, job CI `ui` |
| P1 | `/ui/call`: gọi thử HTTP (text + ghi âm AudioWorklet), bảng trích xuất, debug request/response, kịch bản mẫu; E2E Playwright |
| P2 | `/ui/livekit`: WebRTC qua `livekit-client` (npm, tải lazy), chỉ báo ai đang nói, nhật ký kết nối, **transcript lời thoại** qua data channel |
| P3 | `/ui/observability`: tổng quan KPI + chi tiết, chất lượng STT/TTS, chi tiết cuộc gọi, chi tiết lượt |
| P4 | Link cũ chuyển hướng 307 sang trang mới; xoá `static/`, `observability_static/` và test của chúng |

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| AC-1 Không thêm process/RAM trên server | UI là file tĩnh (`ui/dist`, 1,2 MB; bundle chính 118 kB gzip) do chính process `bot` phục vụ (`src/callbot/transports/http/ui.py`); `docker-compose.prod.yml` không đổi. Đo local (Docker): `bot` 210 MiB lúc rảnh. Đo trên EC2 sau deploy: *chưa deploy* |
| AC-2 Build trong Docker multi-stage, không build trên EC2 | `Dockerfile` stage `ui` (`node:22-alpine`), image cuối chỉ `COPY --from=ui /ui/dist`; đã build cả stack bằng `docker compose up -d --build` |
| AC-3 `/ui/*` phục vụ được, F5 ở route con không 404 | `SpaStaticFiles`; `tests/transports/http/test_ui_mount.py` (fallback, asset thiếu 404 thật, cache `immutable` cho `assets/`, `no-cache` cho `index.html`) |
| AC-4 Đủ tính năng trang cũ | Checklist §4.1 của plan đã tick đủ; `ui/src/features/call/CallPage.test.tsx`, `ui/e2e/call.spec.ts` |
| AC-5 Logic là hàm thuần có unit test | Reducer `features/call/model/callMachine.ts`, `features/livekit/model/session.ts`; `lib/audio/wav.ts`, `lib/api/demoDebug.ts`, `features/observability/model/*` — mỗi file có `*.test.ts`. ESLint cấm component gọi `fetch`/import API |
| AC-6 Type từ OpenAPI, CI bắt lệch | `scripts/export_openapi.py` (`--check` trong `make check`), `npm run api:types`; job CI `ui` `git diff --exit-code` trên `schema.d.ts` |
| AC-7 Trang cũ chạy tới P4 rồi chuyển hướng | `add_legacy_redirects` trong `ui.py`; `test_legacy_pages_redirect_to_new_ui`, `test_legacy_redirects_are_not_part_of_the_api_contract` |
| Riêng tư của dashboard (chuyển từ test cũ) | `ui/src/features/observability/privacy.test.ts`: chỉ `api.ts` gọi `/internal/observability`; không có `patient_id`, `appointment_id`, `utterance`, `audio_url`, `langfuse`, `.jsonl`, URL ngoài |
| Transcript LiveKit không làm hỏng cuộc gọi, không log PII | `CallBridge._publish_transcript` (`call_bridge.py`); `test_call_bridge_publishes_transcript_for_each_line`, `test_transcript_publish_failure_does_not_break_call` |
| `/livekit/token` thiếu package trả 503 rõ ràng | `livekit_token.py`; `test_token_returns_503_when_livekit_package_missing` |

## File liên quan

- `ui/` (mới): cấu hình (`package.json`, `package-lock.json`, `vite.config.ts`, `eslint.config.js`, `tsconfig*.json`, `playwright.config.ts`), `openapi.json`, `e2e/`, `src/**`
- Backend: `src/callbot/transports/http/ui.py` (mới), `main.py`, `config.py`, `demo.py` (response model), `livekit_token.py`; `src/callbot/transports/livekit/call_bridge.py`
- Đã xoá: `src/callbot/transports/http/static/`, `src/callbot/transports/http/observability_static/`, `tests/frontend/`, `tests/observability/test_dashboard_frontend.py`
- Cấu hình: `config/http.yaml` (`ui_dist_dir`), `Dockerfile`, `.dockerignore`, `.gitattributes`, `docker-compose.yml` (volume `traces`), `Makefile`, `.github/workflows/ci.yml` (job `ui`, `e2e`), `.env.example`
- Script/test: `scripts/export_openapi.py`, `tests/transports/http/test_ui_mount.py`, `test_calls.py`, `test_auth.py`, `test_livekit_token.py`, `tests/transports/livekit/test_call_bridge_mapping.py`
- Tài liệu: `README.md`, `docs/plans/ui-vite-react.md`, `docs/voice-observability-dashboard.md`, `docs/reference/http-api.md`, `docs/reference/livekit-voice-pipeline-2026-09-24.md`

## Luồng hiện tại

```text
Build (GitHub Actions / docker build)
  -> stage ui: npm ci -> tsc -b -> vite build -> dist/ (index.html + assets/<hash>.*)
  -> stage python: COPY dist -> /app/ui, UI_DIST_DIR=/app/ui

Runtime (process bot, không process mới)
  GET /, /demo/, /demo/livekit-demo.html, /observability/  -> 307 -> /ui/...
  GET /ui/<route>                 -> index.html (no-cache); router phía trình duyệt
  GET /ui/assets/<hash>.*         -> file (immutable 1 năm)
  /ui/call          -> /v1/calls, /v1/calls/{id}/turn, /demo-api/*        (Bearer key người dùng nhập)
  /ui/livekit       -> /livekit/token -> LiveKit Cloud <- worker (audio + data "callbot.transcript")
  /ui/observability -> /internal/observability/*  (API chỉ đọc, bật ở local)

Hợp đồng API
  FastAPI app.openapi() -> ui/openapi.json -> openapi-typescript -> ui/src/lib/api/schema.d.ts
```

## Quy trình xác minh

```powershell
make check                        # ruff + pytest + scripts/export_openapi.py --check
cd ui
npm ci
npm run check                     # eslint + prettier --check + tsc -b + vitest
npm run build
npm run e2e                       # cần backend thật: docker compose up -d (hoặc xem job e2e trong ci.yml)
docker build --target ui ..       # lockfile hợp lệ với npm 10 của Node 22
```

## Kết quả xác minh cục bộ (2026-09-25)

Python chạy trong venv có đúng phiên bản CI (FastAPI 0.141.1, Pydantic 2.13.5, Starlette 1.7.0 — khớp
`uv.lock`), không dùng Python toàn cục của máy dev (FastAPI 0.116, thiếu `soxr`).

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | Pass (2547 passed, 13 skipped) |
| `python scripts/export_openapi.py --check` | Pass |
| `npm run check` (ui/) | Pass (179 tests, 19 files) |
| `npm run build` (ui/) | Pass — không cảnh báo |
| `npm run e2e` (backend uvicorn + Redis + `CLINIC_BACKEND=sim`) | Pass (2/2: outbound CONFIRMED, inbound im lặng → TRANSFERRED) |
| `docker build --target ui .` | Pass (npm 10; sau khi thêm `livekit-client`, không thêm thư viện nào sau đó) |
| `docker compose up -d --build` | Pass ở bản P1 (24-09) — `/ready`, `/ui/`, `/ui/call`, asset, `/livekit/token` đều 200. Bản P2–P4 chưa build lại bằng Docker |

## Ghi chú

- **CI lần đầu đỏ (commit `3b1f08f`), đã sửa:** job `ui` — `overview.ts` sai Prettier sau khi bỏ `export`; job `e2e` — Redis service để `save` mặc định nên bot từ chối khởi động (`save must be empty`), thêm `config set save ""`; sau đó bot đòi `OPENAI_API_KEY` vì `pull_request` chạy trên commit merge với `main`, nơi `engine.yaml` đã bật `name_fallback_provider: openai` (`bce7072`) — job e2e đặt `NAME_FALLBACK_PROVIDER=none`, `SEMANTIC_FALLBACK_ENABLED=false` (chạy offline, chỉ-luật). Đã tái hiện và chạy lại trên clone sạch (không `.env`, Redis `redis:7.4-alpine` mặc định): `npm run check`, `npm run build`, e2e 2/2 pass.
- **Test CallBridge chưa chạy ở đâu cả:** `tests/transports/livekit/test_call_bridge_mapping.py` bị `importorskip("livekit")`; máy dev và job CI (`.[dev,speech]`) đều chưa cài `livekit`, nên hai test transcript mới cũng bị bỏ qua. Nên thêm `.[livekit]` vào job test CI.
- **LiveKit chưa ghi trace:** worker tạo orchestrator không kèm tracer, nên cuộc gọi LiveKit không hiện trên Observability; chỉ đường HTTP có dữ liệu.
- **Observability API không có auth:** chỉ bật ở local (`docker-compose.yml`); production giữ tắt.
- **npm 11 (máy dev) vs npm 10 (Docker/CI):** npm 11 không ghi peer dependency `@types/dom-mediacapture-record` của `livekit-client` vào lockfile → `npm ci` của npm 10 lỗi. Đã khai báo tường minh; thêm thư viện mới thì kiểm tra bằng `docker build --target ui .`.
- **TypeScript ghim `~5.9`:** `typescript-eslint` 8.70 chỉ hỗ trợ `<6.1`, `openapi-typescript` 7 cần `^5`.
- **Máy dev nên cập nhật Python deps** (`pip install -U -e ".[dev,speech]"`): FastAPI 0.116 sinh `openapi.json` hơi khác bản 0.141 của CI nên `make check` báo lệch.
- **Production chưa đổi:** chưa deploy. Trên EC2 còn thiếu `TTS_PROVIDER=vbee` trong `/opt/callbot/.env` (worker production crash vì OpenAI TTS 403) — việc riêng, chờ người vận hành.
