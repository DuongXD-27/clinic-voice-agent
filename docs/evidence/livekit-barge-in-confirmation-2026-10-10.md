# Evidence: Ngắt lời (barge-in) trên LiveKit lúc được lúc không — 10/10/2026

Phạm vi: đường LiveKit, phần xác nhận người gọi ngắt lời khi bot đang nói
(`speech/turn/interruption.py`, `speech/asr/pipeline.py`, `CallBridge.cancel`). Không đổi config,
không đổi luồng chốt lượt (TurnController) hay ASR.

| # | Lỗi | Kết quả |
|---|---|---|
| 1 | Gate đòi hai partial ASR liên tiếp "hội tụ" (validator ACCEPT) — GipFormer decode lại cả câu nên hiếm khi có cặp như vậy | **Sửa** — đủ chữ có nghĩa + đủ lâu + giọng rõ hơn nền là ngắt, không cần hai partial giống nhau |
| 2 | Gate chỉ được xét khi có partial mới; GipFormer không phát lại partial khi chữ không đổi | **Sửa** — xét lại partial mới nhất trên mỗi frame VAD còn là tiếng nói |
| 3 | Người gọi trả lời bằng chữ của câu bot bị coi là tiếng bot vọng lại (chỉ so chữ), kể cả khi đường truyền không có vọng | **Sửa** — bỏ so chữ khi đường truyền đã cho thấy không vọng |
| 4 | Cửa sổ độ ổn định giữ chữ của đoạn ASR đã bỏ; chữ ngắn lật qua lại làm partial dài sau bị DROP | **Sửa** |
| 5 | `CallBridge.cancel` chờ đóng request TTS rồi mới xoá hàng đợi phát | **Sửa** — tắt tiếng trước, đóng request sau |
| 6 | Một chữ nghe nhầm (GipFormer nghe "OK" thành "ĐẤY" → "ĐÂY") ngắt được bot qua đường "hội tụ" | **Sửa** — một chữ không phải câu trả lời không tự ngắt lời bot |
| 7 | `barge_in_eval` dùng audio bot sinh 30/09 (câu thoại trước đợt chuẩn hoá 08/10) nhưng so với template mới — số đo có tiếng vọng sai từ khi nhánh nhận đợt chuẩn hoá (merge c453edc, 09/10) | **Sửa bộ đo** — câu bot lấy từ cache TTS tĩnh đang chạy production (`--bot-audio static`, mặc định) |

## Chẩn đoán từ log cuộc gọi thật

24 log worker LiveKit 08–09/10 (`temp/livekit-logs/worker-2026100[89]*.log`, DEBUG — có quyết định
gate từng partial). Gom theo lần người gọi nói chen lúc bot nói (có ít nhất một partial):

| | Số lần |
|---|---|
| Lần chen lời có partial | 155 |
| Bot dừng (xác nhận ngắt lời) | 79 |
| Bot nói tiếp hết câu | **76** |

Lý do gate từ chối từng partial: validator WAIT (độ ổn định UNKNOWN) 166, chưa đủ 200 ms / chỉ có từ
đệm 44, coi là tiếng bot vọng lại 27, SNR thấp 21, DROP vì "dao động" 16, DROP khác 18. Lần được
xác nhận thì trễ từ lúc VAD báo tới lúc bot dừng: p50 1,32 s, p75 1,94 s, p90 2,75 s (68% quá 1 s)
— người gọi nghe như bot "vẫn nói tiếp".

**Gốc lỗi 1–2.** `_passes_gate` cũ chỉ cho qua khi `TurnValidator` trả ACCEPT, tức partial hiện tại
"hội tụ" với partial trước (fuzz ≥ 60, không ngắn đi), hoặc final. GipFormer streaming là
chunked-offline: mỗi 0,3 s decode lại cả câu, phần đầu câu đổi chữ liên tục, nên hai partial liên
tiếp thường không đủ giống; và partial chỉ được phát khi chữ đổi, nên câu nói rõ ràng chỉ có một
partial không bao giờ có "partial thứ hai" để hội tụ. Final thực tế không tới lúc bot nói: VAD và
ASR dùng cùng bộ phân loại và cùng `end_silence_ms`, VAD báo speech_end trước nên đoạn ASR bị bỏ
trước khi chốt (78/79 lần xác nhận trong log là qua partial hội tụ, 1 qua luật câu trả lời ngắn,
không lần nào qua final).
Ví dụ thật (09/10):

- `ĐẦU ƠI` → `NHIỀU NGƯỜI MỘT CÁI TẤT` → `VỪA CÓ CÁI TẤT` → … — 6 partial, 3,6 s, không lần nào hội tụ.
- `TỪ LÂU TIẾP XÚC` → `TỪ LÂU THẤY KHÔNG` → `TỪ LÂU TIẾP XÚC` → … — không ngắt được.
- Gemini Live: `hết luôn.`, `từ xưa đến giờ.` — một partial rồi thôi, bot nói tiếp.

Có ngắt được hay không phụ thuộc hai lần decode liên tiếp có tình cờ giống nhau không — đúng hiện
tượng "lúc được lúc không".

**Gốc lỗi 3.** `_is_echo_of_bot` so partial với cả câu bot (1–2 từ phải trùng nguyên văn, từ 3 từ
so mờ ≥ 70) mà không xét đường truyền có tiếng vọng hay không: `CHỊ` (câu bot nào cũng có "anh
chị"), `OK ANH ĐỒNG Ý`, `CHO ANH CHỌN KHUNG` bị coi là tiếng bot trên cuộc gọi web không hề có vọng
(AEC trình duyệt; `echo_path=unknown`, `coverage=0.00`).

**Gốc lỗi 4.** Cửa sổ độ ổn định (`TranscriptEvidenceTracker`) chỉ reset khi có final; đoạn ASR bị
bỏ lúc bot nói không có final nên chữ của nó ở lại. Trong cùng một ứng viên, `HAI TỶ` → `HAI THẾ` →
`HAI TỶ` làm cả `CÓ AI THẤY KHÔNG` (4 từ) bị DROP vì "dao động".

## Sửa

`InterruptionController._gate` (docstring module có đủ điều kiện):

- Điều kiện chặn giữ nguyên: ≥ 200 ms, có chữ có nghĩa, không phải tiếng bot vọng lại, SNR ≥
  `interruption_min_snr_db`, `TurnValidator` không DROP. "Dao động" chỉ DROP khi chính partial
  hiện tại là chữ ngắn (≤ 2 từ).
- Đủ bằng chứng để ngắt khi một trong các điều kiện:
  - câu trả lời/lệnh ngắn rõ ràng (như 08/10: ≥ 0,3 s, SNR ≥ 10 dB, ASR ≥ 0,7);
  - ≥ 2 chữ có nghĩa và partial hội tụ hoặc final;
  - **mới:** ≥ 2 chữ có nghĩa, ≥ 0,4 s từ lúc VAD báo, SNR ≥ 10 dB, ASR ≥ 0,7 nếu chỉ 2 chữ — chỉ khi
    đường truyền không có tiếng vọng; có vọng thì giữ đòi partial hội tụ như trước.
- Một chữ không phải câu trả lời ("ĐÂY", "MÌNH") không tự ngắt lời bot, kể cả khi hội tụ.
- `on_speech_frame`: `STTPipeline._drain_vad` gọi trên mỗi frame VAD còn là tiếng nói; xét lại
  partial mới nhất nếu lần trước nó chỉ thiếu thời lượng.
- Đường truyền không vọng (policy `acoustic`): một câu bot phát 2 s mà VAD không mở ứng viên nào
  (vọng nghe được mở ứng viên ngay, barge_in_eval 12/12 câu, trễ 0,09 s), và mic lúc xét không có
  bản sao tiếng bot. Khi đó không so chữ với câu bot nữa. `text` và `three_state` giữ cách cũ.
- Pipeline reset cửa sổ độ ổn định khi bỏ đoạn ASR (`TurnEvidence.reset_transcript`).
- `CallBridge.cancel`: xoá hàng đợi phát và huỷ vòng phát trước, rồi mới chờ đóng request TTS.
- Log INFO khi xác nhận (không có chữ): `interruption: barge-in confirmed reason=… after_s=… words=…
  echo_path=… echo_clear=…` để đếm số lần và độ trễ ngắt lời trên log production.

## Bộ đo `barge_in_eval` lệch chữ từ 08/10

Chạy `barge_in_eval` trên HEAD (chưa sửa), web echo −30 dB: bot "tự ngắt lời" 6/12 câu chỉ có tiếng
vọng — số đo 08/10 (trước khi nhánh nhận đợt chuẩn hoá câu thoại) là 0/12. Trace từng partial: tiếng vọng là audio `temp/noise-bench/bot_tts.wav`
(sinh 30/09) đọc câu thoại cũ — "DẠ VINMEX XIN NGHE EM LÀ TRỢ LÝ ẢO AI CỦA TỔNG ĐÀI ANH CHỊ VUI LÒNG",
"EM XIN PHÉP CHUYỂN MÁY CHO NHÂN VIÊN ĐỂ HỖ TRỢ ANH CHỊ THÊM" — trong khi câu bot đưa vào
InterruptionController là template sau đợt chuẩn hoá 08/10 (77be770: "Tổng đài Vinmec xin nghe. Em
là trợ lý ảo AI…", "Em xin chuyển máy tới nhân viên…"). Partial dài dần, khớp mờ với câu bot tụt dưới
70, hội tụ → xác nhận. Production không có lệch này (TTS đọc đúng chữ của câu bot).

Sửa: `--bot-audio static` (mặc định) lấy audio Vbee 8 kHz của cache TTS tĩnh 2026-10-08-v1 (đang
phát trên production, đúng chữ template), đưa lên 16 kHz. Cache không có `ASK_ATTENDANCE` (luôn kèm
thông tin lịch) nên thay bằng `CONFIRM_CONFLICT` (cùng loại câu hỏi có/không). `--bot-audio wav` giữ
để so với số đo cũ. Mọi số đo dưới đây chạy lại bằng bộ đo đã sửa, cho cả code trước và sau.

## Kết quả đo

`barge_in_eval --bot-audio static --set speaker_gate_mode=off`, code trước (HEAD e8a6de9) → sau. Bộ
`caller` có 39 lần chen lời, trong đó 10 lần chỉ nói "Ừ" (đúng thiết kế là không ngắt lời bot);
`repeat` = người gọi lặp lại chữ bot vừa nói (giọng TTS), `repeat_real` = giọng thật nói lại cụm
chữ của câu bot (bot còn nói ít nhất 0,8 s); `other` = người khác chen vào. Số liệu lấy từ log từng
điều kiện (không chạy được hết ma trận trong phiên đo — thiếu web echo −20/−10 dB và phone −20
"later", −10 dB).

**Không có tiếng vọng (cuộc gọi web có AEC trình duyệt, SIP không vọng):**

| Điều kiện | Bot tự ngắt | Người gọi chen lời được xác nhận | Trễ xác nhận p50 | Lặp chữ bot (TTS) | Lặp chữ bot (giọng thật) | Người khác chen | Mất chữ người gọi |
|---|---|---|---|---|---|---|---|
| web, câu đầu | 0 → 0 | 18 → **23**/39 | 1,19 → **0,90** s | 0 → **8**/10 | 2 → **13**/38 | 6 → 6/20 | 0,333 → 0,333 |
| web, câu sau | 0 → 0 | 16 → **21**/39 | 1,15 → **0,89** s | 0 → **7**/10 | 2 → **16**/38 | 4 → 5/20 | 0,385 → 0,385 |
| phone, câu đầu | 0 → 0 | 16 → **20**/39 | 1,28 → **0,93** s | 0 → **7**/10 | 2 → **9**/38 | 4 → 5/20 | 0,381 → 0,381 |
| phone, câu sau | 0 → 0 | 14 → **19**/39 | 1,37 → **1,10** s | 0 → **6**/10 | 1 → **10**/38 | 3 → 5/20 | 0,488 → 0,488 |

**Có tiếng vọng** (đường truyền có vọng giữ đòi partial hội tụ như trước):

| Điều kiện | Bot tự ngắt | Người gọi chen lời được xác nhận | Lượt lẫn câu bot |
|---|---|---|---|
| web echo −30 dB, câu đầu | 0 → 0 | 18 → 18 | 0 → 0 |
| phone echo −30 dB, câu đầu | 0 → 0 | 22 → 26 | 4 → 2 |
| phone echo −30 dB, câu sau | 0 → 0 | 15 → 15 | 0 → 0 |
| phone echo −20 dB, câu đầu | 0 → 0 | 16 → 16 | 1 → 1 |

Chữ người gọi gửi tới engine không đổi ở mọi điều kiện (mất chữ, lượt lẫn câu bot giống hệt) —
bản sửa chỉ đổi lúc bot dừng, không đổi nội dung lượt.

**Âm thanh nền không có người gọi** (`eval/noise-bench/barge_noise_eval.py`, 24 trial mỗi điều
kiện, bot bị ngắt lời):

| Nền | Trước → sau |
|---|---|
| Nhiễu văn phòng −15 / −8 / −3 dB | 0 → 0 / 0 → 0 / 0 → 0 |
| Nhiều người nói (babble) −12 / −6 dB | 22 → 22 / 20 → 21 |
| Một người khác nói (voice2) −12 / −6 / 0 dB | 14 → **18** / 14 → **18** / 15 → **19** |

Người khác nói thành câu gần mic ngắt được bot nhiều hơn (+4/24): với hệ thống, đó cũng là "người
nói câu có nghĩa"; chỉ phân biệt được bằng giọng (xem Còn mở).

## Kiểm chứng

| Lệnh / test | Kết quả |
|---|---|
| `tests/speech/turn/test_barge_in_confirmation.py` (mới, 30 ca) | Pass; trên code cũ 20 ca thất bại — 12 do hành vi (tái hiện đúng lỗi), 8 do chưa có `on_speech_frame` |
| `test_barge_in_confirms_on_a_vad_speech_frame_when_asr_sends_no_new_partial`, `test_discarded_asr_segment_does_not_leak_into_the_next_segment_stability` (`tests/speech/test_pipeline_asr_segments.py`) | Pass; cả hai thất bại trên code cũ |
| `test_barge_in_silences_playout_before_waiting_for_the_tts_request_to_close` (`tests/transports/livekit/test_call_bridge_mapping.py`) | Pass; thất bại trên code cũ |
| `ruff check` / `ruff format --check` (src, tests, eval/noise-bench) | Pass |
| `STT_EVAL_ENABLED=false PYTHONPATH=src python -m pytest -q` | 5187 passed, 9 skipped |

## Còn mở

- **Người khác / TV nói gần mic ngắt được bot** (voice2 14 → 18/24). Cổng giọng người gọi
  (speaker gate) mới chạy trên lượt đã chốt, cần ≥ 1–1,5 s audio — quá chậm để chặn ngắt lời.
- **Câu trả lời một chữ có độ tin cậy GipFormer thấp** ("KHÔNG" 0,66, "OK" nghe thành "ĐẤY") không
  ngắt được bot; vẫn thành lượt sau khi bot nói xong (lời chen giữ riêng).
- **Đường truyền có tiếng vọng** giữ cách cũ (đòi partial hội tụ): ngắt lời ở đó vẫn chậm và không
  đều như trước.
- **Bot dừng nhưng lượt bị bỏ sau đó** (từ đệm, cổng giọng chặn): bot im tới hẹn giờ im lặng (8 s)
  rồi hỏi lại. Có thể thêm "nói lại câu bị ngắt" khi ngắt lời không thành lượt.
