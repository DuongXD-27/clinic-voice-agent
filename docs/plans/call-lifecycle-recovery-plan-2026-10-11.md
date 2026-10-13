# Plan: cúp máy, TTS/ASR lỗi và barge-in trên cuộc gọi realtime (thay PR 89)

**Owner:** Hưng (làm cả TTS, LiveKit và Engine) · phần STT (`speech/asr/`, `speech/turn/`) phối hợp Việt · **Viết:** 11/10/2026 · **Sửa:** 11/10/2026 (thêm bảng quy tắc §2, gộp còn 2 nhánh) · **Base:** `develop` (`9a1eeef`)
**Thay cho:** PR 89 `feat/phone-boundary-prd21-dev-eval` (Dương). PR này sẽ đóng vì tách từ `358fb60` và conflict với code STT mới. Code của PR chỉ dùng làm tham khảo, port có chọn lọc. Commit nào lấy lại code của Dương thì ghi `Co-authored-by`.
**Không làm:** script eval điện thoại PH-01..30 (`scripts/phone_*`, `result/*/phone`).

## Nhánh

| Nhánh (tách từ `develop`) | Phase | Vì sao gộp / tách |
|---|---|---|
| `feature/call-lifecycle-recovery` | 1 cúp máy · 2 TTS lỗi · 3 ASR lỗi / mất audio | Cả ba cùng sửa vòng đời `CallBridge` (`aclose`, cờ dừng, hàng đợi) và Phase 2, 3 dùng chung `run_system_error` của Engine. Tách nhánh thì phase sau phải chờ phase trước merge rồi rebase |
| `feature/tts-w4-playback-control` | 4 barge-in | Việc khác hẳn (phần câu đã nghe, guardrail xác nhận); tách từ `develop` sau khi nhánh trên đã merge |

Trong nhánh 1, mỗi phase là một nhóm commit riêng và được test local xong mới sang phase sau. Xong cả 3 phase mới mở PR vào `develop`. Test trên staging xong mới gom `develop → main`.

## Dòng gửi PM (dán vào task sheet)

| Ngày | Task | Gửi PM |
|---|---|---|
| T2 12/10 | Tiếp nhận PR 89 + tái hiện lỗi cúp máy | Tiếp nhận phần việc của PR 89 (cúp máy, TTS/ASR lỗi) để làm lại trên `develop` mới, tránh conflict với code STT. Chốt quy tắc xử lý cho từng tình huống (cúp máy khi đang ghi lịch, TTS lỗi, STT lỗi, barge-in) và tái hiện lỗi khách cúp máy trên LiveKit để xác định đúng event phát hiện cúp máy trước khi sửa. |
| T2 12/10 | Khách cúp máy giữa chừng (R-36) | Xử lý khách cúp máy giữa chừng (R-36, GC-LIVE-05): bot kết thúc phiên ngay và không gửi thêm lệnh ghi nào tới Clinic Mock. Lịch đã ghi thành công thì giữ nguyên kết quả; lệnh chưa rõ Clinic đã nhận hay chưa thì đánh dấu cần đối soát, không gửi lại. Dừng TTS, đóng request Vbee và dọn sạch media/session để không còn lượt im lặng hay chuyển máy giả sau khi khách đã cúp. |
| T3 13/10 | TTS lỗi giữa cuộc gọi (R-39) | Xử lý TTS lỗi giữa cuộc gọi (R-39, GC-STR-05): khi Vbee lỗi, bot phát câu chuyển máy đã thu sẵn bằng giọng Vbee và chuyển nhân viên với SYSTEM_ERROR, thay vì im lặng rồi rớt máy. Clinic chỉ ghi chuyển máy tối đa một lần; lịch đã ghi xong thì giữ nguyên kết quả, lệnh chưa rõ kết quả thì chờ đối soát, không ghi thêm. |
| T4 14/10 | STT lỗi / mất audio | Xử lý khi STT hỏng hẳn hoặc mất audio từ phía khách: STT lỗi 3 lần liên tiếp thì bot báo chuyển máy (SYSTEM_ERROR) thay vì im lặng; mất audio thì đóng cuộc gọi như khi khách cúp máy, không tính là khách im lặng và không tạo kết quả nghiệp vụ giả. Đổi thiết bị mic không làm rớt cuộc gọi. Không thay đổi cách STT chốt lượt hiện tại. |
| T5 15/10 | Barge-in phía TTS | Hoàn thiện barge-in đủ 4 thao tác của hợp đồng: khi khách nói chen, bot dừng phát ngay và báo cho Engine bot đã kịp nói tới câu nào, để câu hỏi xác nhận chưa nói hết không bị tính là đã hỏi (tránh ghi hủy/xác nhận khi khách chưa nghe câu hỏi). Đo thời gian từ lúc khách nói chen tới lúc bot im làm số liệu cho GC-LIVE-03. |
| T6 16/10 | Gate W5: merge `develop → main` | Test toàn bộ trên staging (cúp máy, TTS lỗi, STT lỗi, barge-in) rồi merge `develop → main` trước khi freeze; tổng hợp evidence cho Gate W5. |

---

## 1. Yêu cầu và hiện trạng trên `develop`

| Yêu cầu | Nguồn | `develop` hiện tại | Phase |
|---|---|---|---|
| Khách gác máy giữa chừng: kết thúc phiên, không gửi thêm lệnh ghi; lệnh đã gửi giữ nguyên | R-36, GC-LIVE-05 | `CallBridge` chỉ nghe event `disconnected` của chính phòng; Engine không có lệnh đóng phiên. Lượt Core đang chạy vẫn ghi Clinic; phiên nằm trong Redis tới hết TTL. Hẹn giờ im lặng tính theo đồng hồ (`TurnController.silence_elapsed_s`), nên nếu bridge không biết khách đã rời thì có thể chạy 3 lượt im lặng rồi **ghi UNREACHABLE/TRANSFERRED sau khi khách đã đi** (Phase 0 kiểm tra) | 1 |
| TTS lỗi giữa lượt: phát câu cố định ghi sẵn, chuyển máy SYSTEM_ERROR | R-39, GC-STR-05 | Lỗi trước chunk đầu (không có fallback, `tts_fallback_provider: null`): `_speak` ném lỗi, job chết, khách nghe im rồi mất máy. Lỗi giữa câu: dừng êm, cuộc gọi chạy tiếp với câu bị cụt | 2 |
| ASR lỗi hẳn / mất audio: không im lặng, không đoán thành im lặng | KT (PH-16 của PR 89), R-08.d | Gemini Live lỗi 3 đoạn liên tiếp thì lỗi nổi lên → `_pipeline_error` → job chết im lặng | 3 |
| Barge-in đủ 4 thao tác: dừng phát, dừng sinh câu trả lời, giữ phần lượt nói dở, reset lượt | Hợp đồng Phụ lục B.2, GC-LIVE-03, GC-STR-03 | Dừng phát + hủy Vbee đã có (PR #70); reset lượt đã có ở STT. Engine luôn coi cả `utterance` là khách đã nghe; trace không có số ms | 4 |

**Không làm trong plan này (có lý do):**
- **Lượt ASR rỗng thành `ASR_EMPTY`** (PH-15 của PR 89). `develop` cố ý bỏ lượt có final rỗng hoặc chỉ có tiếng bot vọng (sửa echo 07–08/10). Gemini Live trả final rỗng cho mọi đoạn chỉ có tiếng ồn hoặc tiếng vọng. Gửi các lượt đó sang Engine sẽ sinh "em chưa nghe rõ" giả và chuyển máy NOT_UNDERSTOOD sai. PRD không yêu cầu. Muốn làm thì Việt phải chốt điều kiện trước.
- **`PhoneAdapter` / `lifecycle_adapter.py`.** Điện thoại đi qua LiveKit SIP vào cùng `CallBridge`, nên `CallBridge` gọi thẳng orchestrator, không thêm lớp trung gian.
- **R-38 (Engine trả lời theo từng đoạn câu)** và chuyển máy thật qua SIP (REFER): ngoài phạm vi.

---

## 2. Quy tắc đã chốt (code và test theo đúng các bảng này)

### 2.1 Khách cúp máy khi đang ghi Clinic (Phase 1)

Từ lúc nhận được ý định đóng (khách rời phòng), **không có request ghi nào rời khỏi bot nữa, kể cả gửi lại cùng key** (đúng nguyên văn R-36 "không gửi thêm lệnh ghi nào"). Lượt Core đang chạy không bị hủy mà được chờ xong.

| Trạng thái lệnh ghi lúc khách cúp | Xử lý | Trạng thái phiên sau khi đóng |
|---|---|---|
| Chưa gửi (cổng chặn trước lần `send` đầu) | Không gửi; journal FAILED `TRANSPORT_CLOSED`; lượt dừng bằng `CallEnded`, **không** chuyển máy SYSTEM_ERROR | `HANGUP` |
| Đang gửi, Clinic trả 200 | Giữ kết quả. Store đã tự purge `CLINIC_COMMITTED` rồi `ENDED` lúc ghi thành công (`redis_store.finish_command` / `complete_turn`) | Giữ `ENDED`, chỉ đặt `transport_closed` |
| Đang gửi, lỗi rõ ràng (4xx, outcome known) | FAILED; không gửi lại (kể cả 409 đọc lại version), không ghi gì thêm | `HANGUP` |
| Đang gửi, không rõ kết quả (timeout, mất kết nối) | **Không gửi lại**; UNKNOWN | Giữ `RECONCILIATION_REQUIRED` |
| Phiên đã purge từ trước (`ENDED`, `CLINIC_COMMITTED`, `RECONCILIATION_REQUIRED`, `EXPIRED`) | Không đổi gì | **Giữ nguyên lý do cũ**, chỉ đặt `transport_closed` — không bao giờ đổi thành `HANGUP` |
| Không có lệnh ghi nào | Đóng | `HANGUP` |

Thứ tự ưu tiên khi đóng: lý do purge đã có > `RECONCILIATION_REQUIRED` (còn PENDING/UNKNOWN) > `HANGUP`.

### 2.2 TTS lỗi (Phase 2)

Phía khách **luôn giống nhau**: phát câu `TRANSFER` ghi sẵn → gửi `HANDOFF_REQUESTED` → kết thúc cuộc gọi. Chỉ phía Clinic khác nhau theo trạng thái. Engine luôn trả `TTSRecovery.utterance = TRANSFER` (câu cố định, qua `output_guard.check_tts_fallback`), có hay không có lượt mới đều vậy.

| Trạng thái lúc TTS lỗi | Lượt điều khiển `TTS_ERROR` | Ghi Clinic | `HANDOFF_REQUESTED` |
|---|---|---|---|
| Đang hội thoại, chưa có lệnh ghi nào, có lịch hẹn | Chạy | TRANSFERRED/SYSTEM_ERROR, **tối đa một lần** (key idempotent của lượt + cờ một lần mỗi cuộc gọi) | `preserve_business_outcome=false` |
| Inbound chưa có lịch hẹn | Chạy | Không ghi gì (gateway trả None như hiện nay), không tạo lịch | `preserve_business_outcome=false` |
| Đã ghi thành công (`ENDED` sau CONFIRMED/CANCELLED/RESCHEDULED/BOOKED) | Không chạy | Không ghi, giữ kết quả | `preserve_business_outcome=true` |
| Đã kết thúc bằng chuyển máy / unreachable (lỗi ở chính câu kết thúc) | Không chạy | Không ghi | `preserve_business_outcome=true` |
| Có lệnh PENDING/UNKNOWN | Không chạy | Không ghi, chờ đối soát | `reconciliation_required=true` |
| Khách đã cúp máy | Không chạy | Không ghi | Không gửi, không phát |

Thiếu audio ghi sẵn thì log `TTS_FALLBACK_AUDIO_MISSING`, vẫn gửi `HANDOFF_REQUESTED` và kết thúc, không crash.

### 2.3 Barge-in đủ 4 thao tác (Phase 4)

| Thao tác (Phụ lục B.2) | Cách làm trong kiến trúc này |
|---|---|
| 1. Dừng phát TTS | Đã có: kiểm tra mỗi frame 20 ms, `clear_queue()`, đóng request Vbee. Phase 4 chỉ đảo thứ tự: `clear_queue()` trước khi chờ đóng request |
| 2. Dừng sinh câu trả lời | **Không có model sinh câu nói để hủy**: câu trả lời là template; LLM chỉ dùng trong trích xuất (`extraction/semantic*.py`, `name_slot_filling.py`). Ngắt lời chỉ xác nhận được khi bot đang nói (`InterruptionController.on_speech_started`), lúc đó lượt Engine đã xong. Khách nói chen **lúc Engine đang xử lý**: không hủy lượt Engine (đang giữ khóa phiên, có thể đã gửi lệnh ghi; thread Python không hủy được). Câu trả lời đó vẫn phát; nếu khách còn đang nói thì ngắt lời "rearmed" cắt ngay khi bot bắt đầu; phần đã nghe tính như thao tác 3 |
| 3. Giữ phần lượt nói dở | Phase 4: tính số câu đã phát trọn và báo Engine; câu hỏi chưa phát trọn thì không tính là đã hỏi |
| 4. Reset trạng thái lượt | Đã có ở STT: bot dừng thì `InterruptionController` về IDLE; `TurnController.on_bot_speaking_changed(False, preserve_candidate=True)` giữ lời chen thành lượt mới; hẹn giờ im lặng khởi động lại sau mỗi lượt |

### 2.4 ASR lỗi và mất audio (Phase 3)

| Tình huống | Xử lý |
|---|---|
| Gemini Live lỗi 1–2 đoạn | Không chuyển máy. Đoạn đó thành final rỗng, lời của đoạn bị mất, khách nói lại (hành vi hiện có của provider) |
| Gemini Live lỗi **3 đoạn liên tiếp** | Chuyển máy SYSTEM_ERROR theo bảng 2.2 (lượt `ASR_ERROR`). Bộ đếm **về 0 ngay khi có một đoạn thành công** (`gemini_live.py`, `failed_in_a_row`) |
| ZipFormer (chạy local) ném lỗi | Lỗi hẳn: chuyển máy SYSTEM_ERROR ngay, không đếm |
| Lỗi cấu hình (`ValueError`), `CancelledError` | Không phải lỗi provider, ném nguyên |
| Số lần chuyển máy do lỗi kỹ thuật | Tối đa **một lần mỗi cuộc gọi** (dùng chung cờ với TTS lỗi) |
| Khách rời phòng (`participant_disconnected` của người gọi / `disconnected`) | Cúp máy (bảng 2.1) |
| Track mic kết thúc bình thường, khách vẫn trong phòng (đổi thiết bị, publish lại) | Không đóng; chờ track mới |
| `AudioStream` của track hiện tại báo lỗi, khách vẫn trong phòng | Mất audio: đóng như cúp máy, không outcome, mã `MEDIA_INPUT_LOST` |
| Không nhận frame audio nào trong `media_stall_timeout_ms` (mặc định 10 s) khi khách vẫn trong phòng và bot không nói | Mất audio, **không phải im lặng**: dừng hẹn giờ im lặng, đóng như cúp máy. **Làm trong Phase 3** (chốt lại 12/10 sau test Phase 1: tải lại trang thì trình duyệt không kịp báo rời phòng, `participant_disconnected` không tới, LiveKit chỉ biết sau ~30 s và trong lúc đó bot đã gửi 1 lượt im lặng cho Engine). Ngưỡng dự kiến ~5 s; đo trước xem tắt mic (không rời phòng) frame còn tới không |

### 2.5 Tần số mẫu của audio dự phòng

Audio ghi sẵn là 8 kHz. Track LiveKit tạo theo `tts.stream_sample_rate` của provider TTS chính (Vbee: `VBEE_SAMPLE_RATE`, mặc định 8000; OpenAI 24000). Loader dự phòng không phụ thuộc cờ cache nên có thể lệch: **resample một lần** cả câu bằng `speech.audio.codec.resample(pcm, 8000, track_rate)` rồi mới chia frame 20 ms theo `track_rate`. Không resample từng frame (tiếng tách ở chỗ nối).

---

## 3. Phase 0 — Chuẩn bị (12/10 sáng)

**Gửi PM:** Tiếp nhận phần việc của PR 89 (cúp máy, TTS/ASR lỗi) để làm lại trên `develop` mới, tránh conflict với code STT. Chốt quy tắc xử lý cho từng tình huống (cúp máy khi đang ghi lịch, TTS lỗi, STT lỗi, barge-in) và tái hiện lỗi khách cúp máy trên LiveKit để xác định đúng event phát hiện cúp máy trước khi sửa.

1. Comment trên PR 89 báo Dương sẽ đóng PR và Hưng làm lại toàn bộ (cả phần Engine). Báo Việt về Phase 3 (chạm `pipeline.py`) và Phase 4 (dùng mốc thời gian của `InterruptionController`).
2. **Tái hiện trên `develop`** (local, worker có `LIVEKIT_AGENT_NAME` riêng, `LIVEKIT_LOG_LEVEL=debug`). Gọi `/ui/livekit`:
   - Đóng tab giữa chừng: event nào bắn (`disconnected` của phòng, `participant_disconnected`, chỉ track kết thúc)?
   - Sau khi đóng tab: bridge có còn chạy hẹn giờ im lặng → 3 lượt im lặng → **ghi TRANSFERRED/UNREACHABLE** không (xem Clinic sim / log `clinic.`)?
   - Tắt mic trên trình duyệt (không rời phòng): frame còn tới không? (quyết định ngưỡng `media_stall_timeout_ms` ở bảng 2.4)
   - Làm tương tự với cuộc gọi SIP (softphone), nếu có.
3. Ghi kết quả vào evidence. Kết quả này chốt event phát hiện cúp máy và có làm watchdog mất audio hay không.

> **Kết quả 12/10** (Docker local, `develop@9a1eeef`, outbound `apt_00417`, ZipFormer, `CLINIC_BACKEND=sim`):
>
> | Ca | Rời phòng | Sau khi rời | Phòng đóng / job bị tắt |
> |---|---|---|---|
> | A | Đóng tab lúc bot đang chào | Không log nào báo khách rời. 1 lượt im lặng gửi Engine (00:26:25), bot đọc câu nhắc vào phòng trống | ~32 s sau `start_call` (`process exiting: parent process shutdown`), không có bước dọn dẹp của `CallBridge` |
> | A (`LIVEKIT_SILENCE_TIMEOUT_MS=3000`) | Đóng tab lúc bot đang chào | **2 lượt im lặng** gửi Engine (00:30:31, 00:30:44); lượt 3 (ghi UNREACHABLE) dự kiến ~00:30:57 | ~28 s sau `start_call`, trước lượt 3 |
> | A2 | Bấm "Kết thúc" lúc bot đang chào | Giống ca A: 1 lượt im lặng (00:34:00) | ~27,5 s sau `start_call` |
>
> **Chốt:**
> - `CallBridge` không phát hiện khách rời. Event `disconnected` đang nghe chỉ tới khi LiveKit đóng phòng (~25–30 s), và job bị tắt ngang nên không đóng phiên Engine (phiên nằm lại Redis tới hết TTL). Rời "đàng hoàng" (nút Kết thúc) hay đóng tab đều như nhau.
> - Bot coi khách đã rời là khách im lặng và gửi lượt im lặng thật cho Engine. Lần đo chưa tới lệnh ghi chỉ vì phòng đóng trước lượt im lặng thứ 3; phòng sống lâu hơn ~6 s là ghi UNREACHABLE sau khi khách đã cúp (trái R-36). Lệnh ghi này được chứng minh bằng unit test ở Phase 1.
> - Phase 1 dùng **`participant_disconnected` của `caller_identity`** để phát hiện cúp máy ngay; giữ `disconnected` làm đường dự phòng.
> - ~~Hoãn watchdog mất audio~~ → **làm trong Phase 3** (bảng 2.4). Test Phase 1 ngày 12/10: tải lại trang giữa cuộc gọi thì `participant_disconnected` không tới; bridge chỉ biết qua `ROOM_DISCONNECTED` ~30 s sau (phiên vẫn đóng đúng, không có lệnh ghi), nhưng trong lúc đó đã gửi 1 lượt im lặng cho Engine. Mất sóng điện thoại / trình duyệt bị tắt ngang sẽ giống vậy.
> - Ngoài lề: `create_static_cache` đọc 73 file WAV trên event loop lúc bắt đầu job (`event loop blocked for 106ms`) → chuyển sang thread trong Phase 1.

---

## 4. Phase 1 — Khách cúp máy (R-36) · nhánh `feature/call-lifecycle-recovery`

**Gửi PM:** Xử lý khách cúp máy giữa chừng (R-36, GC-LIVE-05): bot kết thúc phiên ngay và không gửi thêm lệnh ghi nào tới Clinic Mock. Lịch đã ghi thành công thì giữ nguyên kết quả; lệnh chưa rõ Clinic đã nhận hay chưa thì đánh dấu cần đối soát, không gửi lại. Dừng TTS, đóng request Vbee và dọn sạch media/session để không còn lượt im lặng hay chuyển máy giả sau khi khách đã cúp.

**Quy tắc:** bảng 2.1.

### Engine
| File | Thay đổi |
|---|---|
| `engine/session/store.py` | `SessionRecord` thêm `transport_closed`, `close_requested` (mặc định `False` để đọc record cũ). Protocol thêm `request_transport_close`, `close_session` |
| `engine/session/redis_store.py` | `request_transport_close`: key riêng `{prefix}:close-intent:{call_id}`, TTL = tombstone, để lượt đang lưu JSON không ghi đè được. `get_session` overlay `close_requested` từ key đó. `close_session` (chạy dưới call lock, idempotent) theo đúng thứ tự ưu tiên của bảng 2.1: đã purge thì giữ lý do; còn PENDING/UNKNOWN thì `RECONCILIATION_REQUIRED`; còn lại `HANGUP`. Đặt `transport_closed`, lưu dạng tombstone. Không bao giờ đặt outcome nghiệp vụ |
| `engine/session/manager.py` | `request_close` (không chờ lock), `close_call` (công bố ý định đóng rồi lấy lock và đóng), `is_transport_closed`. `_check_retired` ném `CallEnded` khi `close_requested`. Gắn cổng ghi (ContextVar, `tools/dispatch.py`) cho mỗi lượt |
| `engine/orchestrator.py` | `request_call_close(call_id)`, `close_call(call_id)` |
| `engine/errors.py` | Thêm `CallEnded` vào `TURN_ABORTING_ERRORS` để không biến thành chuyển máy SYSTEM_ERROR (chuyển máy cũng là một lệnh ghi) |
| `engine/tools/clinic_gateway.py` | **Cổng ghi** trong `_write`, kiểm tra **trước mọi lần `send`** (lần đầu, gửi lại sau lỗi chưa rõ, gửi lại sau 409). Bị chặn ở lần đầu: `journal.failed(command, "TRANSPORT_CLOSED")` + `CallEnded`. Bị chặn ở lần gửi lại sau lỗi chưa rõ: UNKNOWN (giữ nguyên đường `_unknown` hiện có). Đặt ở gateway (không ở HTTP client như PR 89) để `CLINIC_BACKEND=sim` cũng có cổng |

**Chỗ race đã chấp nhận:** khách cúp máy đúng lúc cổng vừa cho qua thì request đó vẫn đi. Nó được tính là "đã gửi trước khi cúp" và xử lý theo các dòng "đang gửi" của bảng 2.1.

### LiveKit (`transports/livekit/call_bridge.py`)
- Phát hiện cúp máy bằng event chốt ở Phase 0 (dự kiến `participant_disconnected` của `caller_identity`, cộng với `disconnected`). Handler `_on_caller_left()`:
  - đặt cờ `_hangup`;
  - gọi `request_call_close` trong thread (không chặn event loop bằng Redis);
  - dừng hẹn giờ im lặng, bỏ các lượt đang chờ trong hàng đợi, báo hết input, hủy `_speak` đang chạy.
- Lượt Core đang chạy trong thread không bị bỏ ngang (`asyncio.shield`) mà được chờ xong.
- `aclose()` luôn gọi `close_call` khi phiên đã mở. Dọn dẹp: `tts.cancel()` (đóng request Vbee), `clear_queue()`, `audio_source.aclose()`. Ghi trace event `call.cleanup` với các cờ boolean (không chứa PII).
- Nhận `CallEnded` / `ReconciliationRequired` sau khi đã cúp máy thì chỉ ghi trace `event_ignored`, không phát âm thanh, không crash job.
- Thêm `livekit.close_call`, `core.close_call` và các event mới vào allow-list trong `tracing/privacy.py`.
- Gộp task TTS 08/10: câu chuyển máy phải phát hết (`wait_for_playout`) rồi mới kết thúc phiên. Thêm test.

### Test (mỗi dòng của bảng 2.1 một test)
- Port và chỉnh từ PR 89 (`test_phone_lifecycle.py`, `test_dispatch_hangup.py`, `test_call_bridge_lifecycle.py`):
  - cúp máy trước khi gửi → không gửi, journal FAILED, không có lệnh `/transfer`, phiên `HANGUP`;
  - cúp máy khi đang gửi, Clinic trả 200 → phiên giữ `ENDED`, không thành `HANGUP`;
  - cúp máy khi đang gửi, 409 → không đọc lại version để gửi lại;
  - cúp máy khi đang gửi, timeout → không gửi lại, UNKNOWN, `RECONCILIATION_REQUIRED`;
  - phiên đã `ENDED` / `RECONCILIATION_REQUIRED` rồi mới cúp → giữ nguyên lý do;
  - cúp máy khi đang nghe / khi bot đang nói / khi lượt Core đang chạy;
  - đóng lặp lại hoặc callback đến muộn → bỏ qua có trace;
  - bot đang chờ Vbee trả chunk đầu thì khách cúp → request bị đóng;
  - sau khi cúp không còn lượt im lặng nào được gửi Engine.
- Local: lặp lại thao tác ở Phase 0. Sau khi đóng tab: không còn lượt im lặng, không có lệnh ghi Clinic; `redis-cli GET` thấy tombstone `HANGUP`; log có `call.cleanup` đủ cờ True.

**Xong khi:** test pass, `make check` pass, lỗi tái hiện ở Phase 0 không còn.

---

## 5. Phase 2 — TTS lỗi giữa lượt (R-39) · nhánh `feature/call-lifecycle-recovery`

**Gửi PM:** Xử lý TTS lỗi giữa cuộc gọi (R-39, GC-STR-05): khi Vbee lỗi, bot phát câu chuyển máy đã thu sẵn bằng giọng Vbee và chuyển nhân viên với SYSTEM_ERROR, thay vì im lặng rồi rớt máy. Clinic chỉ ghi chuyển máy tối đa một lần; lịch đã ghi xong thì giữ nguyên kết quả, lệnh chưa rõ kết quả thì chờ đối soát, không ghi thêm.

**Quy tắc:** bảng 2.2 và 2.5.

### Phát hiện lỗi (`CallBridge._speak`)
Ném `TTSPlaybackError` (không mang message gốc) khi:
- gateway ném lỗi trước chunk đầu (provider chính lỗi và không có, hoặc cũng lỗi, fallback);
- stream kết thúc với `error_code` (lỗi giữa câu);
- stream không trả byte nào mà không phải do bị ngắt lời.

Bị ngắt lời hoặc khách cúp máy thì **không** phải lỗi TTS.

### Engine
| File | Thay đổi |
|---|---|
| `engine/types.py` | `CallerInput.control_event: Literal["TTS_ERROR","ASR_ERROR"]` (không có text/audio/silence). `TTSRecovery(utterance, action, preserve_business_outcome, reconciliation_required)`; `utterance` luôn là `TRANSFER` |
| `engine/session/manager.py` | `run_system_error(call_id, process, event)` chạy dưới cùng lock với các lượt khác, rẽ nhánh đúng theo bảng 2.2: khách đã cúp → `CallEnded`; phiên đã kết thúc → trả `None` (không chạy lượt); còn PENDING/UNKNOWN → `ReconciliationRequired`; còn lại chạy một lượt điều khiển ở `last_completed_turn + 1` |
| `engine/orchestrator.py` | `handle_tts_error(call_id) -> TTSRecovery` (luôn trả `utterance=TRANSFER`, kể cả khi không chạy lượt). Trong `_process`, lượt điều khiển bỏ qua trích xuất, không ghi vào lịch sử, không tính là im lặng hay không hiểu, đi thẳng `dialogue.transfer(ctx, "SYSTEM_ERROR")` |
| `engine/policy/output_guard.py` | `check_tts_fallback`: chỉ cho câu `TRANSFER` tĩnh, không lộ thông tin lịch |

### Phát câu dự phòng
- **Audio:** `assets/tts/static/2026-10-08-v1/073_TRANSFER_...wav` (Vbee Ngọc Huyền, 8 kHz, đã nghe duyệt, có `audio_sha256` trong manifest). Không cần file `system-error-8k.wav` riêng như PR 89.
- **Loader** (`speech/tts/fixed_fallback.py`): load release trực tiếp bằng `StaticAudioCache` (kiểm checksum như cache hiện có), không phụ thuộc `TTS_STATIC_ENABLED`. Chỉ phát khi text của asset **trùng nguyên văn** `TTSRecovery.utterance` (= `TRANSFER`). Resample theo §2.5.
- **`CallBridge._recover_tts_error()`** chạy tối đa một lần mỗi cuộc gọi (cờ dùng chung với Phase 3):
  1. dừng hẹn giờ im lặng và STT pipeline;
  2. gọi `handle_tts_error` trong thread;
  3. `tts.cancel()`, `clear_queue()`;
  4. phát audio ghi sẵn theo từng frame (ngắt lời được); publish transcript "bot: TRANSFER";
  5. gửi `HANDOFF_REQUESTED` (kèm `preserve_business_outcome`, `reconciliation_required`);
  6. ghi trace `tts.fallback_played` / `call.handoff_requested`;
  7. kết thúc cuộc gọi.
- Áp dụng cho cả lỗi ở lời chào.

### Tài liệu
Sửa `docs/plans/tts-w3-w6.md`, mục 6 "Không làm": dòng "phát câu từ cache khi TTS lỗi" mâu thuẫn với R-39. Ghi rõ: chỉ phát đúng câu `TRANSFER` cố định, trùng nguyên văn.

### Test (mỗi dòng của bảng 2.2 một test)
- Port và chỉnh `test_phone_tts_recovery.py`:
  - Vbee lỗi trước chunk đầu → phát TRANSFER ghi sẵn, Clinic ghi TRANSFERRED/SYSTEM_ERROR đúng một lần, cuộc gọi kết thúc;
  - Vbee lỗi giữa câu → tương tự;
  - inbound chưa có lịch hẹn → không ghi, không tạo lịch, vẫn phát và handoff;
  - lỗi sau khi đã ghi thành công → không chạy lượt, không ghi, `preserve_business_outcome=true`, vẫn phát TRANSFER;
  - lệnh UNKNOWN → không ghi, `reconciliation_required=true`;
  - khách đã cúp máy → không phát, không handoff;
  - TTS lỗi lần hai trong cùng cuộc gọi → không ghi lần hai;
  - thiếu audio dự phòng → không crash, vẫn handoff;
  - track 24 kHz (provider OpenAI) → audio được resample, đúng thời lượng;
  - bị ngắt lời giữa câu → không bị coi là lỗi.
- Local: worker với `VBEE_API_TOKEN=sai`, cache bật. Lời chào phát từ cache. Câu động đầu tiên lỗi 401 → bot đọc câu chuyển máy (giọng Vbee), cuộc gọi kết thúc, Clinic sim ghi TRANSFERRED/SYSTEM_ERROR (outbound `apt_00417`).

**Xong khi:** test pass; thử local đúng như mô tả; đã sửa `tts-w3-w6.md`.

---

## 6. Phase 3 — ASR lỗi / mất audio · nhánh `feature/call-lifecycle-recovery`

**Gửi PM:** Xử lý khi STT hỏng hẳn hoặc mất audio từ phía khách: STT lỗi 3 lần liên tiếp thì bot báo chuyển máy (SYSTEM_ERROR) thay vì im lặng; mất audio thì đóng cuộc gọi như khi khách cúp máy, không tính là khách im lặng và không tạo kết quả nghiệp vụ giả. Đổi thiết bị mic không làm rớt cuộc gọi. Không thay đổi cách STT chốt lượt hiện tại.

**Quy tắc:** bảng 2.4.

| File | Thay đổi |
|---|---|
| `speech/asr/pipeline.py` | Chỉ bọc lời gọi `asr.stream(self._asr_frames(), **options)` trong `_drain_asr`. **Giữ nguyên `options` có `stream_context`** (Gemini Live). Lỗi provider đổi thành `ASRProviderError` (không mang message gốc); `CancelledError` và `ValueError` thì ném nguyên. Không động tới `controller.py` |
| `engine/orchestrator.py` | `handle_asr_error(call_id)`: dùng chung `run_system_error` của Phase 2, nhánh `ASR_ERROR`, cùng bảng 2.2 |
| `transports/livekit/call_bridge.py` | `_consume_turns` bắt `ASRProviderError` → `handle_asr_error` → bot nói câu TRANSFER (qua TTS bình thường; trúng cache thì không tốn tiền; TTS cũng lỗi thì đi đường Phase 2) → `HANDOFF_REQUESTED` → kết thúc. Trace `STT_PROVIDER_ERROR` |
| | Mất audio theo bảng 2.4: lỗi `AudioStream` của track hiện tại → đóng như cúp máy, mã `MEDIA_INPUT_LOST`. Track kết thúc bình thường → không đóng. Watchdog không có frame (nếu Phase 0 cho thấy cần) |

**Test (mỗi dòng của bảng 2.4 một test):**
- Gemini lỗi 2 đoạn rồi 1 đoạn thành công rồi lỗi 2 đoạn → không chuyển máy (bộ đếm đã về 0);
- Gemini lỗi 3 đoạn liên tiếp → chuyển máy SYSTEM_ERROR đúng một lần;
- ZipFormer ném lỗi → chuyển máy ngay;
- `ValueError` cấu hình → không bị đổi thành chuyển máy;
- lỗi ASR sau khi Clinic đã ghi → không ghi thêm;
- TTS lỗi rồi ASR lỗi trong cùng cuộc gọi → chỉ một lần chuyển máy;
- stream mic lỗi → đóng, không có lượt im lặng giả;
- publish lại mic → không đóng;
- (nếu làm watchdog) không có frame quá ngưỡng → đóng, không gửi lượt im lặng;
- các test STT hiện có của Việt pass nguyên.
- Local: chọn `gemini_live` với `GEMINI_API_KEY=sai`, nói 3 lần → bot nói câu chuyển máy rồi cuộc gọi kết thúc. Nhờ Việt review `pipeline.py`.

**Xong khi:** test pass, Việt duyệt, thử local đúng như mô tả. Mở PR nhánh `feature/call-lifecycle-recovery` → `develop`.

---

## 7. Phase 4 — Barge-in: phần câu đã nói + đo thời gian dừng · nhánh `feature/tts-w4-playback-control`

**Gửi PM:** Hoàn thiện barge-in đủ 4 thao tác của hợp đồng: khi khách nói chen, bot dừng phát ngay và báo cho Engine bot đã kịp nói tới câu nào, để câu hỏi xác nhận chưa nói hết không bị tính là đã hỏi (tránh ghi hủy/xác nhận khi khách chưa nghe câu hỏi). Đo thời gian từ lúc khách nói chen tới lúc bot im làm số liệu cho GC-LIVE-03.

**Quy tắc:** bảng 2.3. Tách từ `develop` sau khi nhánh `feature/call-lifecycle-recovery` đã merge. Task T4 07/10 trong `tts-w3-w6.md`.

### TTS / LiveKit
- **Phần đã phát:** khi bị ngắt, `played_ms` = thời lượng đã `capture_frame` trừ phần còn trong hàng đợi của `AudioSource`. Quy ra **số câu đã phát trọn** theo ranh giới câu (`. ? !`), dùng mốc thời gian từng ký tự giống `InterruptionController.echo_text`. Câu chỉ phát một phần thì tính là **chưa nghe** (an toàn: hỏi lại thay vì ghi).
- **Trace** (không chứa text):
  - `barge_in_confirm_ms`: từ lúc VAD báo người gọi bắt đầu nói (`heard_from`) tới lúc xác nhận ngắt;
  - `barge_in_stop_ms`: từ lúc xác nhận tới khi `clear_queue` xong;
  - `played_ms`, `sentences_heard` / `sentences_total`.
- **Sửa nhỏ:** `CallBridge.cancel()` gọi `clear_queue()` **trước** khi chờ đóng request Vbee.
- Chuỗi gọi: `_speak` trả về khi bị ngắt → gọi `orchestrator.on_bot_interrupted(...)` trong thread → rồi mới lấy lượt tiếp theo. Vòng lặp của bridge chạy tuần tự nên không có race với lượt nói chen.

### Engine
- `orchestrator.on_bot_interrupted(call_id, turn, sentences_heard)` ghi vào context của lượt vừa xong (dưới call lock) rằng câu hỏi nghiệp vụ của lượt đó (`ctx.question`) **chưa được nghe** nếu câu cuối chưa phát trọn.
- Guardrail xác nhận/hủy (`guardrails.py`, điều kiện `question.turn == item.turn - 1`) không nhận AGREE cho câu hỏi chưa nghe. Dialogue hỏi lại đúng câu hỏi đó, ví dụ `CANCEL_RECONFIRM`.

### Test
- ngắt hai lần liên tiếp → không phát lẫn audio lượt cũ;
- tính số câu đã phát (cache / stream / ngắt trước chunk đầu);
- **hủy lịch**: bị ngắt trong lúc đọc lại lịch, khách nói "đúng rồi" → không có lệnh hủy, bot hỏi lại câu xác nhận lần hai;
- ngắt sau khi câu hỏi đã phát trọn → xác nhận như bình thường;
- khách nói lúc Engine đang xử lý (thao tác 2) → lượt Engine không bị hủy, không ghi trùng; câu trả lời bị cắt thì câu hỏi tính là chưa nghe;
- toàn bộ test Engine hiện có pass.
- Local: luồng hủy, nói chen "đúng rồi" lúc bot đọc ngày giờ → bot hỏi lại câu xác nhận. Ghi `barge_in_confirm_ms` / `barge_in_stop_ms` của khoảng 10 lần ngắt (web, và SIP nếu có).

**Xong khi:** test pass; có bảng số ms cho GC-LIVE-03 / EV-036. Mở PR → `develop`.

---

## 8. Lịch dự kiến

| Ngày | Việc |
|---|---|
| T2 12/10 | Phase 0 (sáng) · Phase 1 |
| T3 13/10 | Phase 2 |
| T4 14/10 | Phase 3 · mở PR `feature/call-lifecycle-recovery` → `develop`, test staging |
| T5 15/10 | Phase 4 (`feature/tts-w4-playback-control`) → `develop`, test staging |
| T6 16/10 | Test staging toàn bộ → PR `develop → main` trước khi freeze (Gate W5) · evidence |

Trễ thì ưu tiên Phase 1 và Phase 2 (R-36, R-39 là yêu cầu đã chốt và GC-LIVE-05 / GC-STR-05 chấm trực tiếp): có thể mở PR nhánh 1 ngay sau Phase 2 và để Phase 3 thành commit tiếp theo. Phase 4 có thể sang tuần 6 (buffer).

## 9. Rủi ro

| Rủi ro | Xử lý |
|---|---|
| Sửa Engine (session, gateway, guardrail) có thể làm lệch luồng nghiệp vụ đã chấm | Không đổi hành vi nghiệp vụ hiện có; chạy đủ test Engine và mentor eval trước khi mở PR |
| Chưa biết event cúp máy và hành vi frame khi tắt mic trên LiveKit/SIP | Phase 0 tái hiện trước khi code |
| `pipeline.py` vẫn đang đổi bên phía Việt | Chỉ sửa một chỗ bọc lỗi; báo Việt trước, rebase ngay trước khi mở PR |
| Ước lượng "đã phát" lệch khoảng ±300 ms (jitter phía client, tốc độ đọc) | Chỉ tính câu đã phát trọn, sai thì nghiêng về "chưa nghe" |
| Nhánh 1 lớn (3 phase) nên PR khó review | Commit tách theo phase; evidence ghi rõ commit nào thuộc phase nào |
| Prod đang dùng hay không dùng static cache | Loader dự phòng không phụ thuộc cờ cache; ảnh Docker đã `COPY assets/tts/static` |

## 10. Sau mỗi nhánh

- Evidence trong `docs/evidence/` theo `TEMPLATE.md` (mỗi PR một file).
- Cập nhật `tts-w3-w6.md` (tiến độ T4 07/10, T5 08/10) và tick task trên sheet.
- Commit chỉ khi được yêu cầu, tên commit theo phase.
