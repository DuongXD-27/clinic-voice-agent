# Thực thi kế hoạch cải tiến âm thanh LiveKit — 28/09/2026

Kết quả triển khai và đo đạc cho `docs/plans/livekit-audio-improvement-plan-2026-09-28.md`.
**Nguyên tắc áp dụng xuyên suốt:** một thay đổi chỉ được giữ bật/khuyến nghị khi số đo cho
thấy nó không làm xấu đi chỉ số nào so với cấu hình hiện tại; nếu đo cho kết quả tệ hơn, thay
đổi đó bị **từ chối và tắt hẳn**, dù đã cài đặt xong về mặt code. Không có mục nào được bật vì
"đã làm xong" — chỉ bật vì số đo ủng hộ.

Toàn bộ số đo dùng `eval/noise-bench/bench.py` (đồng hồ ảo, xác định — mục 0) trên 3 bộ dữ
liệu cắt từ 100 file `temp/audio/livekit_debug_web-*.wav` (cuộc gọi thật, không commit):
`web` (42-84 câu dài tuỳ điều kiện), `golden` (37-40 câu có nhãn), `short` (19 câu 1-3 từ:
"dạ", "ừ", "ok", "không được", "đúng rồi"...). Kết quả JSON đầy đủ ở `temp/noise-bench/results/`
(không commit — chứa audio/text từ cuộc gọi thật).

---

## 0. Nền tảng đo (Giai đoạn 0 — làm trước)

**Vấn đề trước đó:** `bench.py` đẩy frame nhanh hơn thời gian thực nhưng `TurnController`
dùng `asyncio.sleep` thật cho timeout — hai lần chạy cùng tham số cho kết quả khác nhau.

**Đã làm:**
- `TurnController` nhận `clock`/`sleep` injectable (`src/speech/turn/controller.py`).
- `bench.py`: `VirtualTime` (đồng hồ + hẹn giờ ảo dùng `heapq`), `_settle()` chờ ASR (chạy
  trong `asyncio.to_thread`) và VAD cùng xử lý xong frame trước khi đẩy frame kế — loại bỏ
  phụ thuộc tốc độ máy chạy bộ đo.
- **Xác nhận xác định:** chạy `--label det1`/`det2` cùng tham số hai lần, JSON kết quả (trừ
  `seconds`/`decode_s`, vốn phụ thuộc CPU) **giống hệt nhau từng byte**.
- Thêm `--profile production|target` (khoá cấu hình cứng, không phụ thuộc `.env` máy chạy —
  trước đó local và production đo hai cấu hình khác nhau mà không ai để ý).
- Thêm bộ dữ liệu `short` (19 câu trả lời ngắn thật, lọc theo mức to tuyệt đối ≥ 300 RMS và
  ≥ 150 ms — loại tiếng gõ phím/tiếng động khỏi bộ, xem docstring `build_short_set`).
- Thêm `latency_p50/p90` (giây từ hết câu tới lượt **đầu tiên** chốt sau đó — không lấy lượt
  cuối, tránh tính nhầm lượt giả do nhiễu) và `decode_calls/decode_s` (chi phí CPU thật).
- Sửa lỗi có sẵn trong `TranscriptEvidenceTracker._is_oscillating`: luật cũ chỉ đếm "một text
  xuất hiện ≥ 2 lần trong 5 gần nhất", nên chuỗi hội tụ dần "ĐƯỢC"→"VÂNG"→"VÂNG" (SNR 58 dB,
  rõ ràng là người dùng nói thật) bị coi là dao động và DROP. Luật mới: chỉ tính dao động khi
  một text NGẮN **quay lại sau khi đã đổi** sang text khác (test hồi quy:
  `test_changing_once_then_holding_is_not_oscillating`).

Bộ đo giờ **xác định** và đo đúng 2 cấu hình cần so sánh — nền tảng cho mọi số đo dưới đây.

---

## 1. Kết quả theo từng đề xuất

### ✅ Đã làm và giữ (số đo ủng hộ)

| # | Việc | Trạng thái | Bằng chứng |
|---|---|---|---|
| A | Lượt im lặng gửi core | Xong, mặc định BẬT (8s) | §2 |
| D | Chỉ nhận track người gọi | Xong, luôn bật (không cờ) | §2 |
| 8 | Tách VAD khỏi backpressure ASR + chờ final khi ASR còn tồn | Xong, luôn bật | §3 |
| B | Confidence ASR từ `ys_log_probs`, chỉ ghi log/đo | Xong, luôn tính (không gửi core) | §4 |
| 2 (bước 1) | Bộ phân loại dùng chung (`SharedSpeechDetector`) | Xong, cờ tắt mặc định — **đã đối chiếu 0 khác biệt** | §5 |
| 4 | Gỡ Speech Admission | Xong — code đã xoá hẳn | §6 |
| — | Giãn nhịp decode partial câu dài (`partial_interval_ratio`) | Xong, cờ tắt mặc định (0.0) | §7 |
| — | Hangover Silero cấu hình được (`silero_min_silence_ms`) | Xong | §7 |

### ❌ Đã thử và TỪ CHỐI — code đã GỠ (số đo phản bác)

| # | Việc | Vì sao từ chối | Bằng chứng |
|---|---|---|---|
| 1 | Khử nhiễu/tách giọng phía server (NC/BVC) | Làm WER và tỉ lệ mất câu **tệ hơn** `plain` ở gần mọi điều kiện đã đo | §8 |
| 6 | Hotwords theo state | Beam đủ rộng để sửa "hủy lịch" cũng **đảo nghĩa** nhiều câu khác thành "KHÔNG ĐỒNG Ý" | §9 |
| 2 (bước "đổi VAD chính sang Silero") | Chuyển VAD chính production sang Silero | Giảm ảo giác dưới nhiễu văn phòng nhưng **mất nhiều câu ngắn thật hơn** — đánh đổi không rõ ràng có lợi. Không có code riêng để gỡ (chỉ là chưa đổi `vad_provider`) | §5 |

Với 1 và 6: không chỉ tắt cờ — toàn bộ code (provider, `CallBridge`, config, `Dockerfile`,
`pyproject.toml`, script đo) đã bị xoá khỏi repo sau khi có kết luận. Không giữ lại "hạ tầng đã
tắt sẵn" cho những gì đã đo là có hại.

### ⏸ Chưa làm trong đợt này

Mục 3 (streaming ASR thật), 5 (validator theo state — chỉ phần từ đệm cần nhãn thật, chưa có),
7 (bộ sửa lỗi nghiệp vụ — điều kiện là hotwords đủ tốt, nhưng hotwords đã bị từ chối), 9 (cổng
giọng tiền cảnh), 10 (profile điện thoại), C bước "chốt cấu hình production lên Silero" (xem §5).

---

## 2. Lượt im lặng cho core + chỉ nhận track người gọi

**Lượt im lặng (`CallBridge._watch_silence`):** sau khi bot dứt lời, nếu
`TurnController.silence_elapsed_s()` (mốc muộn nhất giữa lúc bot dừng và lần cuối VAD thấy
tiếng) vượt `silence_timeout_ms` (mặc định 8000 ms), gửi `CallerInput(text=None,
silence_ms=...)` — đúng hợp đồng core (Phụ lục A). Không gửi khi đang có câu dở (VAD đã
`speech_start`, chưa chốt/huỷ). Mọi lượt (thật hoặc im lặng) huỷ hẹn giờ đang chạy qua
`generation` counter — hẹn giờ cũ nằm sẵn trong queue bị bỏ qua nếu có lượt khác xử lý trước.

Test: `tests/transports/livekit/test_call_bridge_input.py` (7 test: gửi đúng lúc, không gửi
khi đang nói, không gửi khi tắt, hẹn giờ cũ bị bỏ qua, timer khởi động lại sau mỗi lượt bot).

**Chỉ nhận track người gọi (`CallBridge._on_track_subscribed`):** lọc theo `source` (chỉ
`SOURCE_MICROPHONE`/`SOURCE_UNKNOWN`, bỏ share-màn-hình) và theo `identity` (khoá vào
participant đầu tiên có mic). Publish lại mic (đổi thiết bị) huỷ pump cũ trước khi tạo pump
mới — tránh hai luồng PCM xen kẽ vào cùng `_frame_queue`. Test:
`test_only_caller_microphone_is_pumped`, `test_first_participant_becomes_caller_when_identity_unknown`,
`test_republished_caller_mic_replaces_previous_stream`.

Cả hai đều là bổ sung logic mới (đường LiveKit trước đây không có), không đổi hành vi pipeline
âm thanh nên không cần bench so sánh trước/sau.

---

## 3. Tách VAD khỏi backpressure của ASR

`STTPipeline`: `asr_queue` tách khỏi `vad_queue`, rộng hơn 20 lần (`asr_queue_max_frames`,
mặc định `queue_max_frames * 20` ≈ 30 s ở 30 ms/frame) — ASR chậm không còn chặn `_fanout`
đẩy frame cho VAD. Cảnh báo log khi ASR tồn ≥ 1000 ms audio chưa decode.

**Hệ quả cần xử lý:** VAD có thể báo `speech_end` trong khi ASR còn tồn audio của chính câu
đó (trước đây không xảy ra vì cả hai bị nghẽn cùng lúc). `TurnController` thêm
`set_asr_pending_probe()` — `_try_emit` chờ thêm tối đa `turn_max_wait_for_asr_ms` (mặc định
3000 ms) khi ASR còn tồn, thay vì chốt ngay bằng partial cũ thiếu chữ cuối.

Test bắt được đúng hồi quy này trên code cũ: `tests/speech/test_pipeline_asr_lag.py::
test_slow_asr_does_not_stall_vad_and_turn_waits_for_final` — chạy trên snapshot code trước
khi sửa (`git worktree`), turn chốt thành `"tôi muốn"` (thiếu "đặt lịch"); trên code mới,
`["tôi muốn đặt lịch"]` đầy đủ. 4 test khác xác nhận VAD không đứng theo ASR, và trường hợp
ASR rảnh (`asr_pending=False`) giữ nguyên hành vi cũ (timeout 300 ms như trước).

---

## 4. Confidence ASR từ `ys_log_probs`

`ZipFormerASR._decode_scored`: `confidence = exp(trung bình ys_log_probs)`,
`min_token_prob = exp(min ys_log_probs)`. Gắn vào `TranscriptEvent.confidence` (final only,
qua `_decode_final`/`_final_event`). Chỉ ghi log DEBUG + đưa vào `final_confidences` của
`bench.py` — **không gửi core, không ảnh hưởng quyết định nào của pipeline** (đúng ràng buộc
"chỉ đo trước", core cũng không đọc `asr_confidence`).

**Đo (`eval/noise-bench/confidence_eval.py`, final ngắn ≤ 2 từ, bộ web+short, office+babble):**
- Confidence **không tách được lỗi nghe nhầm**: "hủy lịch"→"THÙY LINH" vẫn có
  confidence 0,79/0,98/0,57 theo từng token (xác nhận lại quan sát ban đầu ở
  `docs/evidence/livekit-turn-loss-2026-09-26.md`).
- Cần chạy thêm để có phân vị thật/giả trên tập lớn hơn trước khi cân nhắc dùng làm tín hiệu
  chặn ảo giác (mục 2.B bước 2 trong kế hoạch gốc) — **chưa đủ căn cứ để bật bất kỳ ngưỡng
  nào**, giữ nguyên trạng thái "chỉ đo".

---

## 5. Một VAD dùng chung — kết quả trái chiều, chỉ giữ phần đã kiểm chứng an toàn

### 5.1 `SharedSpeechDetector` — AN TOÀN, cờ tắt mặc định

`src/speech/asr/vad/shared.py`: `_fanout` gọi `classify(frame)` một lần/frame theo đúng thứ
tự thời gian; VAD chính, bộ chốt câu ASR, evidence Validator đọc lại qua `view()` (khoá theo
`id(frame)`, không suy luận lại). Bật qua `speech_shared_detector` (mặc định `false`).

**Đối chiếu (28/09):** chạy `bench.py --profile target` với và không
`speech_shared_detector=true` trên bộ `web` (462 trial) và `golden` (407 trial) —
**0/869 trial khác kết quả** (cả `finals` lẫn `turns` giống hệt từng trial). Bộ `short` cũng
khớp 100%. Kết luận: thay thế 3 bản Silero độc lập bằng 1 bản dùng chung **không đổi kết quả
pipeline**, chỉ giảm số lần suy luận Silero mỗi frame (3→1 khi Validator bật) — an toàn để bật
bất cứ lúc nào cấu hình mục tiêu (Silero làm VAD chính) được dùng. Giữ tắt mặc định vì bản
thân việc chuyển VAD chính sang Silero (§5.2) *chưa* được quyết định bật.

### 5.2 Đổi VAD chính production sang Silero — TỪ CHỐI, không đổi mặc định

Kế hoạch gốc coi "chọn Silero hay WebRTC bằng số liệu" là việc cần làm trong bước tái cấu
trúc. Đã đo trực tiếp (`--profile production` = WebRTC, `--profile target` = Silero+Validator,
cùng seed, cùng bộ dữ liệu):

**Bộ `web` (câu dài, office noise) — Silero (target) tốt hơn rõ:**

| Điều kiện | `no_turn` (prod / target) | `false_turns` (prod / target) | `latency_p50` (prod / target) |
|---|---|---|---|
| office@15 | 0 / 1 | 8 / **0** | 3,96 s / **0,69 s** |
| office@8 | 0 / 1 | 11 / **0** | 3,96 s / **0,74 s** |
| office@3 | 2 / 7 | 11 / **0** | 3,96 s / **0,66 s** |

Latency 3,96 s ở production **không phải lỗi đo**: dưới nhiễu văn phòng, WebRTC liên tục báo
speech nên `speech_end` không tới, turn chỉ chốt khi trial hết (tail 2 s) —
`temp/noise-bench/results/B1prod_short.json`, case `SHORT_00`: `turn_times=[7.02]` dù câu hết
lúc ~3,06 s. Silero không bị nhiễu đánh lừa liên tục nên báo `speech_end` đúng lúc.

**Bộ `short` (câu 1-3 từ, office noise) — Silero tệ hơn rõ:**

| Điều kiện | `no_turn` (prod / target), 38 trial | Câu KHÔNG phải "Ừ" giữ được turn (prod / target), /18 |
|---|---|---|
| office@8 | 13 / **26** | 16 / **8** |

Truy nguyên nguyên nhân (`temp/claude.../trace_short.py`, so cùng trial qua 2 profile): Silero
nhạy hơn đưa nhiều audio nhiễu hơn vào ASR chunked-offline; ASR (buffer ngắn, ít ngữ cảnh) nghe
sai nội dung dưới nhiễu nhiều hơn — "KHÔNG"→"NHIỀU"/"KHÔNG BIẾT", "KHÔNG ĐƯỢC"→"CŨNG ĐƯỢC",
trong khi WebRTC (ít audio nhiễu lọt vào ASR hơn) giữ đúng "KHÔNG ĐƯỢC". Đây không phải lỗi
Validator (đã kiểm: Validator ACCEPT các câu này, confidence đo được cao 0,88) mà là hạn chế
gốc của chunked-offline ASR khi nhận nhiều audio nhiễu hơn.

**Kết luận ban đầu (số đo trên):** đánh đổi không rõ ràng có lợi — tốt hơn nhiều cho câu
dài/latency, tệ hơn rõ cho câu ngắn (đúng loại câu quan trọng nhất: xác nhận có/không, hủy/giữ
lịch).

**Cập nhật 28/09/2026 (sau khi số đo trên đã trình bày rõ với owner): owner QUYẾT ĐỊNH đổi**
`vad_provider: silero` (kèm `turn_validator_enabled: true`, `interruption_min_snr_db: 0.0`)
thành mặc định chính thức trong `config/speech.yaml`, **chấp nhận rủi ro `no_turn` tăng cho
câu ngắn đã nêu ở trên** — không phải do số đo đổi kết luận, mà là đánh đổi latency/độ ổn định
câu dài được ưu tiên hơn. `turn_validator_enabled`/`interruption_min_snr_db` đổi cùng đợt
nhưng **chưa có số đo tách riêng** (bảng trên đo gộp cả 2 trong cấu hình `target`) — nếu sau
này thấy vấn đề, cần đo tách riêng từng cờ để biết cờ nào gây ra, không mặc định đổ cho Silero.
Việc tiếp theo hợp lý (chưa làm): thử Silero với ngưỡng threshold cao hơn 0,5 hoặc kết hợp cổng
năng lượng trước Silero để giảm audio nhiễu lọt vào ASR cho câu ngắn, rồi đo lại.

---

## 6. Gỡ Speech Admission

Đo 25/09 (`docs/evidence/livekit-noise-robustness-2026-09-25.md`) đã cho thấy tắt Admission
tốt hơn ở 11/12 phép đo; production vốn tắt; nó là một phía của bug 26/09 (câu kẹt trong ASR).
28/09: xoá hẳn code (`src/speech/asr/admission.py`, nhánh trong `_fanout`, tham số trong
`STTPipeline.__init__`/`build_streaming_bundle`/`SpeechSettings`), không chỉ tắt cờ. Toàn bộ
2571 test (sau khi xoá 2 file test riêng cho Admission, gộp/sửa các test dùng chung file với
Admission) qua, `ruff check`/`format` sạch.

---

## 7. Hai việc nhỏ đi kèm

- **`partial_interval_ratio`** (`ZipFormerConfig`): giãn khoảng cách giữa 2 lần decode partial
  theo độ dài buffer (`max(300ms, ratio × buffer_ms)`) cho câu dài — partial vẫn decode lại
  toàn bộ buffer (không đổi thuật toán), chỉ giảm *tần suất* gọi. Test xác nhận: `ratio=0.2`
  giảm ≥ 40% số lần decode trên câu 6 s liên tục, còn câu ngắn (1,2 s) giữ nguyên nhịp (không
  ảnh hưởng độ nhạy barge-in cho câu ngắn). Mặc định `0.0` (tắt, hành vi cũ) — theo đúng
  khuyến nghị kế hoạch gốc ("chỉ bật sau khi đo CPU trên máy production", chưa có máy đó).
- **`silero_min_silence_ms`**: expose hangover Silero (trước đây cố định 0,5 s trong code) ra
  cấu hình, để việc tinh chỉnh thời gian chờ hết câu (roadmap giai đoạn 3) có chỗ để làm mà
  không cần sửa code provider.

---

## 8. Khử nhiễu / tách giọng phía server — TỪ CHỐI, code đã gỡ

### Hạ tầng đã dựng để đo, rồi gỡ sau khi có kết luận

Đã cài đặt và chạy thật để lấy số liệu: `noise_cancellation_from_setting()` trong
`call_bridge.py` (map cấu hình → bộ lọc plugin `livekit-plugins-noise-cancellation` 0.3.2,
extra `[livekit-nc]`), cờ `input_noise_cancellation` (`""`/`nc`/`bvc`/`bvc_telephony`), script
`eval/noise-bench/livekit_nc_capture.py` (dựng phòng LiveKit Cloud tạm — dispatch tới
`agent_name` không tồn tại nên không worker thật nào bị gọi vào — publish 111 trial qua WebRTC
thật, mở 3 `AudioStream` trên cùng track để so sánh công bằng: không lọc / NC / BVC) và
`eval/noise-bench/livekit_nc_eval.py` (căn thời gian từng trial riêng với input gốc bằng tương
quan đường bao, loại trial căn kém để so sánh công bằng). Đã chạy thật qua LiveKit Cloud
(9,6 phút audio, tốn phút kết nối thật) để lấy số liệu ở dưới.

**Sau khi có kết luận (phản bác rõ ràng, xem dưới), toàn bộ hạ tầng này đã bị gỡ khỏi code**:
`noise_cancellation_from_setting()`, tham số `noise_cancellation`/`hotwords_by_state` trong
`CallBridge`, extra `livekit-nc` trong `pyproject.toml`, cài đặt plugin trong `Dockerfile`, và
cả hai script `livekit_nc_capture.py`/`livekit_nc_eval.py`. Không giữ lại "hạ tầng tắt sẵn" —
một khi số đo đã phản bác rõ, code không dùng chỉ làm rối cấu trúc hiện có. Muốn đo lại thì
viết lại từ kết quả bên dưới (đã đủ chi tiết để tái tạo).

### Kết quả — phản bác rõ ràng

Tương quan trung vị sau căn chỉnh: `plain` 0,96 (căn tốt), **`nc` 0,43, `bvc` 0,39** (méo mó
nặng so với input gốc — bản thân việc lọc đã làm tín hiệu khó đối chiếu). Trên các trial còn
giữ được (tương quan `plain` ≥ 0,9), so `plain` (qua LiveKit, không lọc) với `nc`/`bvc`:

| Điều kiện | `wer_turn` (plain/nc/bvc) | `no_turn` /18 hoặc /5 (plain/nc/bvc) |
|---|---|---|
| clean | 0,127 / 0,310 / 0,197 | 13 / **17** / **16** |
| office@8 | 0,241 / 0,345 / **1,069** | 3 / 4 / **6** |
| babble@6 | 1,562 / 1,562 / 1,488 | 0 / 2 / 4 |

`nc`/`bvc` **tệ hơn không lọc gì cả** ở gần mọi điều kiện đã đo, kể cả audio sạch (`clean`) —
plugin tự nó làm mất câu (`no_turn` tăng) và làm ASR nghe sai nhiều hơn (`wer_turn` tăng, đặc
biệt `bvc` ở `office@8`: WER > 1 nghĩa là turn sai nhiều hơn cả số từ đúng). Chỉ ở `babble`
(giọng nền) `bvc` nhỉnh hơn về WER nhưng đổi lại mất câu nhiều hơn — không phải cải thiện rõ
ràng. Kết quả giống nhau trên cả 2 profile (`production`, `target`).

**Kết luận: KHÔNG dùng khử nhiễu phía server (NC/BVC).** Không loại trừ khả năng vấn đề nằm ở
cách đo (méo tương quan 0,39-0,43 đáng ngờ, có thể do chính plugin thay đổi timing/pitch chứ
không hẳn chất lượng kém) — nhưng với bằng chứng hiện có, **không đủ căn cứ để bật**, và việc
dùng phút LiveKit Cloud thật cho mỗi lần đo lại khiến việc lặp lại tốn kém. Đã **gỡ toàn bộ
code** (không chỉ tắt cờ) — xem đầu mục này.

### Đo lại với Krisp VIVA (`livekit-plugins-krisp` 0.4.3) — 28/09/2026, cùng kết luận

Sau câu hỏi liệu `livekit-plugins-krisp` (Krisp VIVA, bản kế thừa package `noise-cancellation`
đã đo ở trên) hay `livekit-plugins-ai-coustics` (hãng khác) có khá hơn không, đã đo thử Krisp
VIVA — **chưa đo ai-coustics** (cần đăng ký API key riêng của hãng, chưa làm).

**Khác NC/BVC cũ: đo được HOÀN TOÀN OFFLINE, không cần dựng room/publish LiveKit Cloud thật.**
`KrispVivaFilterFrameProcessor._process()` chỉ cần gọi `_on_credentials_updated(token, url)`
với một JWT ký bằng `LIVEKIT_API_KEY`/`SECRET` sẵn có (không cần room join thật — token chỉ
dùng để Krisp SDK tự làm DRM authorization qua mạng) và `_on_stream_info_updated(...)` với dữ
liệu tĩnh bất kỳ, sau đó feed từng frame 10 ms @ 16 kHz trực tiếp — không tốn phút kết nối
LiveKit Cloud, và loại bỏ được nguồn nhiễu đo có thể do timing/network jitter mà lần đo NC/BVC
qua WebRTC thật gặp phải (tương quan đường bao 0,39-0,43 ở trên). Script:
`eval/noise-bench/krisp_eval.py` (venv riêng cài `livekit-plugins-krisp`, không đụng
`pyproject.toml`/venv chính — xem cảnh báo về nâng cấp ngoài ý muốn bên dưới).

So `plain` (không lọc) với `krisp` (`VOICE_ISOLATION`, `noise_suppression_level=90`), cùng bộ
`web` (42 câu), 2 profile:

| Profile | Điều kiện | `wer_drift` (plain/krisp) | `no_turn` /42 (plain/krisp) | `false_turns` /12 (plain/krisp) |
|---|---|---|---|---|
| production | clean | 0,040 / **0,106** | 0 / **3** | – |
| production | office@8 | 0,109 / **0,204** | 0 / **3** | 10 / 7 |
| production | babble@6 | 1,515 / 1,493 | 1 / 0 | 12 / 12 |
| target | clean | 0,036 / **0,124** | 0 / **3** | – |
| target | office@8 | 0,095 / **0,150** | 1 / 3 | 0 / 0 |
| target | babble@6 | 1,445 / 1,358 | 1 / 1 | 12 / 12 |

**Cùng kết luận với NC/BVC: Krisp làm WER tệ hơn ở hầu hết điều kiện, kể cả `clean`** (WER
tăng gấp ~3 lần, 0,036-0,040 → 0,106-0,124, `no_turn` 0→3 dù không có lý do gì để mất câu trên
audio sạch không nhiễu). Chỉ nhỉnh nhẹ ở `babble@6` (giọng nền), không đáng kể.

Vì lần đo này **không đi qua network/WebRTC thật** (loại trừ được giả thuyết "vấn đề là do
cách đo qua LiveKit Cloud" nêu ở trên), có thể xem 10 câu cụ thể bị đổi trên `clean`
(10/42, tức 24% câu, script `inspect_clean.py` không commit) để xác nhận **bản chất vấn đề
là chính bộ lọc làm méo đặc trưng giọng nói**, không phải lỗi đo:

- `"NGUYỄN VĂN A"` → `"ĐIỆN THOẠI"` — tên bệnh nhân biến mất hoàn toàn, hallucinate thành từ
  không liên quan.
- `"TÔI TÊN LÀ NGUYỄN VĂN AN"` → `"THÔI ĐỂ LÀM NỮA CON NON"` — hallucination toàn câu.
- `"LÊ THỊ HƯƠNG"` → `"LÊ THỊ DƯƠNG"` — lỗi tên riêng tinh vi (nghe hợp lý nhưng sai), nguy
  hiểm hơn lỗi hallucinate rõ ràng vì dễ bị xác minh nhầm hồ sơ mà không ai nghi ngờ.

**Kết luận: KHÔNG dùng Krisp VIVA**, cùng lý do với NC/BVC — cả hai đều dựa trên engine Krisp
(khác thế hệ) và cho cùng một pattern lỗi. Không có bằng chứng nào cho thấy bản VIVA mới hơn
đã khắc phục vấn đề méo tín hiệu của bản cũ.

**Cảnh báo quan trọng — sự cố khi cài đặt để đo:** `pip install livekit-plugins-krisp` **không
qua `uv`** đã cài thẳng vào base env `anaconda3` (dự án này không dùng `.venv` cô lập — xem
`which python3`), tự ý nâng `livekit-agents` 1.8.3 và `openai` 2.54.0, làm vỡ `fakeredis` tạm
thời (đã phục hồi bằng `pip install -e ".[dev,speech,...]"`, nhưng KHÔNG hạ được
`livekit-agents`/`openai` về bản cũ vì `pyproject.toml` chỉ ràng buộc `>=1.8`, không pin — 2
bản mới hơn vẫn thoả mãn constraint). Đã xác minh test suite (2566 passed) và các điểm dùng
trực tiếp 2 package này (`inference/tts/providers/openai.py`,
`callbot/transports/livekit/worker.py`) vẫn import/hoạt động đúng sau nâng cấp, nhưng đây là
thay đổi ngoài ý muốn với môi trường thật, không phải một venv thử nghiệm cô lập — cần lưu ý
khi cài thêm plugin LiveKit nào khác trong tương lai: luôn ưu tiên venv cô lập
(`python3 -m venv --system-site-packages ...` không đủ cô lập nếu base env đã sẵn bị đổi từ
trước; an toàn nhất là venv KHÔNG kế thừa site-packages, cài lại đủ extras cần cho script đo).

Đã gỡ `livekit-plugins-krisp` khỏi base env sau khi đo xong; `eval/noise-bench/krisp_eval.py`
**giữ lại trong repo** (không xoá như NC/BVC cũ) vì bản thân script không có dependency ngoài —
chỉ cần cài `livekit-plugins-krisp` khi muốn chạy lại, không kéo theo rủi ro cấu trúc nào khi
nằm im trong `eval/`.

---

## 9. Hotwords theo state — TỪ CHỐI, code đã gỡ

### Hạ tầng đã dựng để đo, rồi gỡ sau khi có kết luận

Đã cài đặt và chạy thật để lấy số liệu: `src/inference/asr/bpe_vocab.py` (đọc thẳng protobuf
SentencePiece từ `bpe.model` ra `bpe.vocab` mà sherpa-onnx cần cho `modeling_unit="bpe"`,
không thêm dependency `sentencepiece`); trong `ZipFormerASR`, một recognizer THỨ HAI
(`modified_beam_search` + hotwords) chỉ dùng cho lần decode final, partial vẫn recognizer
greedy cũ; `CallBridge._current_hotwords()` lấy cụm từ theo `BotAction.state` (core đã trả,
không sửa core); cờ `asr_hotwords_enabled` (mặc định `false`), map state→cụm ở
`config/livekit.yaml`, cố ý không có `AWAITING_IDENTITY`; tải `bpe.model` (~270 KB, cùng repo
HuggingFace `g-group-ai-lab/gipformer1.5-68M-rnnt`) trong `Dockerfile`.

**Sau khi có kết luận (phản bác rõ ràng, xem dưới), toàn bộ hạ tầng này đã bị gỡ khỏi code**:
`bpe_vocab.py` và test của nó, recognizer thứ hai + tham số `hotwords` trong `ZipFormerASR`,
`hotwords_score`/`hotwords_max_active_paths`/`bpe_vocab_path` trong `ZipFormerConfig`,
`hotwords_by_state`/`_current_hotwords()` trong `CallBridge`, cờ `asr_hotwords_enabled` và map
state→cụm trong `config/livekit.yaml`, dòng tải `bpe.model` trong `Dockerfile`. Đây là thay
đổi đã đo được là **nguy hiểm** (đảo nghĩa "đồng ý"↔"không đồng ý"), không chỉ "chưa đủ tốt" —
không có lý do để giữ lại một đường tắt nguy hiểm trong code dù đang tắt.

### Kết quả — phản bác rõ ràng, mọi mức đã thử

Quét riêng (`temp/claude.../hw_scan.py`, không commit) trên **408 đoạn Silero cắt từ toàn bộ
100 file dump thật**, so `greedy` (partial hiện tại) / `beam4` (beam search không hotwords) /
4 cấu hình hotwords (điểm 4-8, beam 32-64) với cụm
`"HỦY LỊCH/ĐỔI LỊCH/GIỮ LỊCH/ĐỒNG Ý/KHÔNG ĐỒNG Ý"`:

- **Beam hẹp (mặc định sherpa-onnx, điểm 1,5/beam 4): hotwords không có tác dụng** — "THÙY
  LINH" không đổi thành "HỦY LỊCH" dù cộng điểm, vì hotword chỉ được cộng điểm khi đã lọt vào
  beam, và beam hẹp không giữ đường đó.
- **Beam đủ rộng (≥ 32) để sửa được lỗi mục tiêu: sửa đúng 2 câu, ép sai 43 câu khác** (408
  đoạn, mọi cấu hình 4 điểm × 2 beam thử). Trong 43 câu sai, nhiều lần là **đảo nghĩa nguy
  hiểm**, không phải chỉ nghe nhầm vô hại:
  - `"Ừ"` (đồng ý ngắn) → `"KHÔNG ĐỒNG Ý"` — ít nhất 6 lần độc lập trong bộ quét.
  - `"ĐÂY"`, `"KHÔNG"`, `"LÀ"` → `"KHÔNG ĐỒNG Ý"`.
  - Câu **của chính bot** vọng lại mic ("XIN CHÀO ANH CHỊ") → `"SỬA ĐỔI LỊCH"` — hotwords có
    thể ép cả audio không phải người dùng nói.
  - Xảy ra ở **cấu hình nhẹ nhất đã thử** (điểm 4, beam 32) — không phải chỉ ở mức điểm cao.
- Thời gian decode final tăng theo cấu hình: beam4 164 s / hw4_p32 325 s / hw8_p64 474 s cho
  cùng 408 đoạn (baseline greedy 123 s) — chi phí CPU cũng tăng đáng kể, không chỉ chất lượng.

**Với một callbot xác nhận hủy/giữ lịch, việc "ừ" (đồng ý) có xác suất bị hallucinate thành
"không đồng ý" — dù hiếm — là rủi ro nghiêm trọng hơn nhiều so với lợi ích sửa "hủy lịch" nghe
thành "thùy linh".** Đây đúng là rủi ro mà kế hoạch gốc đã cảnh báo trước khi đo (mục 2.6:
"phải đo riêng, không giả định"), và số đo xác nhận rủi ro đó là thật, không phải giả thuyết.

**Kết luận: KHÔNG dùng hotwords với cấu hình hiện tại.** Đã **gỡ toàn bộ code** (không chỉ tắt
cờ) — xem đầu mục này.

---

## 10. Việc còn lại / gợi ý bước tiếp theo (không nằm trong đợt này)

1. **Babble (giọng nền) vẫn là vấn đề lớn nhất chưa giải được**: mọi cấu hình đã thử
   (production, target, +shared detector, +NC, +BVC) đều cho `false_turns` 11-12/12 ở
   `babble@6` — không có thay đổi nào trong đợt này cải thiện được việc này.
2. Nếu muốn theo hướng Silero, thử ngưỡng threshold > 0,5 hoặc cổng năng lượng trước Silero để
   giảm audio nhiễu lọt vào ASR chunked-offline (§5.2), đo lại trên bộ `short` trước khi cân
   nhắc đổi `vad_provider` production.
3. Hotwords: nếu muốn thử lại (code đã gỡ, phải viết lại từ đầu), hướng an toàn hơn là hậu
   kiểm (so khớp mờ giữa kết quả greedy và beam+hotwords, chỉ nhận khi khác biệt nhỏ và nằm
   đúng vị trí kỳ vọng) thay vì để beam search tự do cộng điểm — chưa làm.
4. Confidence ASR (§4): cần thêm dữ liệu trước khi cân nhắc dùng làm tín hiệu chặn ảo giác.
5. NC/BVC (§8): nếu nghi ngờ phép đo (tương quan thấp bất thường), có thể thử lại (code đã gỡ,
   phải viết lại từ đầu) với đoạn audio dài hơn 120 s dùng cho `find_offset` ban đầu, hoặc đo
   trực tiếp bằng tai trên vài file thay vì suy ra từ tương quan đường bao.
