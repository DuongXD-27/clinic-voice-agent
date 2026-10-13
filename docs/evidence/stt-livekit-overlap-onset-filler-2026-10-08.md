# Evidence: STT LiveKit — người gọi nói đè lúc bot bắt đầu nói, đuôi câu, "Ừ" rõ ràng, echo — 08/10/2026

Phạm vi: chỉ phần trước engine (audio người gọi → VAD → GipFormer → chốt lượt). Đợt sửa buổi tối
08/10, sau lượt review cùng ngày. Mốc so sánh là working tree trước đợt này (gồm các thay đổi chưa
commit của lượt review 08/10), lưu thành commit object `af7f9c7` (`git stash create`). Bench: `eval/noise-bench` (deterministic, đồng hồ ảo).

| # | Việc | Kết quả |
|---|---|---|
| 1 | Người gọi đang nói dở thì bot bắt đầu nói | **Sửa** — trước đây cả câu bot không có ứng viên ngắt lời, lời người gọi bị bỏ |
| 2 | Final decode cả ~1,1 s im lặng đuôi → câu ngắn đổi chữ | **Sửa** — cắt tới frame cuối còn là giọng + 300 ms; giữ partial khi final ngắn lật chữ |
| 3 | "Ừ" to, rõ của người gọi bị bộ lọc từ đệm bỏ | **Sửa** — "ừ/ờ/dạ" qua khi ASR ≥ 0,95 và SNR ≥ 10 dB |
| 4 | Tiếng động thành một từ ("ÔNG" 0,28 khi đập bàn) | **Sửa** — câu 1–2 từ, ASR < 0,5, không phải từ trả lời thì bỏ |
| 5 | Cuộc gọi web bị coi là "có tiếng vọng" → cắt chữ người gọi nhắc lại câu bot | **Sửa** — chỉ tính vọng khi VAD nghe thấy nó |
| 6 | Echo trễ ≥ 0,6 s (SIP) không được nhận ra | **Sửa** — độ phủ chỉ tính phần câu bot đã đến hạn vọng về |
| 7 | Echo 1–2 từ cuối câu bot ("KHÔNG Ạ") thành câu trả lời giả | **Sửa** — chỉ khi mic có tiếng vọng |
| 8 | Lần ngược đầu câu theo năng lượng (thay pre-roll cố định) | **Có code, TẮT** (`onset_lookback_ms: null`) — làm mất lượt trên bộ web |
| 9 | Cổng giọng người gọi: chấm theo đoạn con 1,5 s, giọng mẫu chỉ từ lượt một giọng, model CAM++ | **Viết lại, ENFORCE** (sau khi đo ở chế độ log trên cuộc gọi thật) — bản cũ (cả lượt) lấy nhầm tiếng điện thoại làm giọng mẫu |
| 10 | Câu trả lời ngắn ("OK EM") không ngắt được bot | **Sửa** — câu ≤ 3 từ trả lời/lệnh, nói ≥ 0,5 s, SNR ≥ 15 dB, ASR ≥ 0,7 được xác nhận ngắt lời |

## 1. Người gọi nói dở lúc bot bắt đầu nói

**Lỗi:** `InterruptionController` chỉ mở ứng viên ngắt lời ở cạnh `speech_start`. Người gọi nói tiếp
trong lúc core trả lời (cửa sổ gộp 700 ms + LLM 1–2 s) thì VAD đã "đang nói" khi bot bắt đầu: cả câu
bot không có ứng viên, `_route_while_bot_speaking` bỏ đoạn ASR mỗi frame, lượt dở bị xoá khi bot dứt
lời. Đuôi vọng câu bot trước cũng bắc cầu VAD sang câu sau theo đúng cách đó.

**Sửa:** `on_bot_started_speaking` mở ứng viên ngay nếu VAD đang có tiếng (`rearmed`). Đường truyền
CHƯA thấy tiếng vọng: giữ đoạn ASR (không DISCARD), hết câu mà chưa xác nhận thì
`AsrSegmentEnd.FINALIZE` (ZipFormer chốt final thay vì bỏ), `TurnController` giữ lượt bắt đầu trước
câu bot và giao khi bot dứt lời; người gọi dừng rồi nói tiếp giữa lúc bot nói thì phần trước được giữ
(`_stash_pre_bot_candidate`). Đường truyền ĐÃ thấy tiếng vọng: như ứng viên thường (bỏ đoạn cũ, giữ
riêng audio mới), so echo với cả câu bot trước.

`barge_in_eval` vị trí "later" (2 câu bot trước, cách 1 s), kênh điện thoại, 12 echo_only + 20 người
gọi (script `later_run.py` của đợt điều tra, không commit):

| Echo −30 dB | Trước sửa | Bản giữ đoạn ASR mọi lúc (loại) | Bản cuối |
|---|---|---|---|
| Lượt giả do echo | 5/12 | 12/12 | **0/12** |
| Bot tự ngắt lời | 0/12 | 10/12 | **0/12** |
| Ngắt lời thật được xác nhận | 0/20 | 16/20 | **14/20** |
| Mất chữ người gọi (recall) | 0,79 | 0,207 | **0,145** |
| Mất trọn câu | 13/20 | 1/20 | **2/20** |

Không echo (−200 dB), bản cuối: 0/12 lượt giả, xác nhận 12/20, mất chữ 0,061, mất trọn câu 1/20.

## 2. Đuôi câu của final

Final decode cả ~1,1 s đuôi (hangover Silero 0,5 s + `end_silence_ms` 0,6 s); câu ngắn đổi chữ:
partial "BÂY GIỜ" 0,94 → final "ĐƯỢC" 0,28; thêm 1,1 s im lặng vào 19 câu ngắn đổi 3–5 câu.

| Biến thể | Kết quả | Quyết định |
|---|---|---|
| Tới frame Silero gắn cờ cuối + 150 ms | short sạch 0,318 → 0,227 nhưng "ĐÚNG KHÔNG" → "ĐÚNG" ("KHÔNG" nhỏ, không gắn cờ) | Loại |
| Tới frame cuối còn là giọng (to trong 25 dB đỉnh câu) + 150 ms | Thêm chữ thừa sau tiếng động cuối ("…BẢY TÁM CHỊ", "…TRÊN"), golden-phone office@8 "DẠ MƯỜI" | Loại |
| Như trên + 300 ms (**chọn**) | web sạch drift 0,036 → 0,040, không mất lượt; office@3 0,177 → 0,173 | **Giữ** |

Kèm luật giữ partial: final ≤ 2 từ, tin cậy < 0,5, kém partial ≥ 0,3 và không nối tiếp partial.

## 3–4. Từ đệm rõ ràng và tiếng động một từ

Độ tin cậy GipFormer của "Ừ/À/ĐÂY" nghe ra từ nhiễu thuần trên 175 lần chạy noise-bench (2685 final):
cao nhất 0,849 / 0,933 / 0,863. "Ừ" thật (cuộc gọi 08/10, to, kéo dài): 0,996–0,998. Câu ngắn thật
khớp decode sạch (136 câu): p5 0,389, 20/136 < 0,5 ("KHÔNG" 0,335 sạch) — nên không chặn chỉ theo độ
tin cậy; chỉ bỏ câu ngắn kém chắc KHÔNG phải từ trả lời ("ÔNG" 0,28, "ĐÂY" 0,31/0,42 ở cuộc gọi thật).
"Ừ" chen lúc bot nói chỉ tính là trả lời khi câu bot là câu hỏi và người gọi nói trong 4 s cuối.

## 5. Nhận nhầm tiếng vọng trên cuộc gọi web

Cuộc gọi 08/10 (web, trình duyệt có AEC): `echo_path=echo` từ câu bot đầu; "HỌ VÀ TÊN CỦA ANH LÀ…" →
"CỦA ANH LÀ…", "NGÀY THÁNG NĂM SINH CỦA ANH LÀ…" → "CỦA ANH LÀ…". Phần vọng còn sót sau AEC (~−55
dBFS) tương quan với tiếng bot nhưng Silero không bắt nên không thể thành chữ. Giờ cần ≥ 30% frame mic
lúc vọng được VAD báo tiếng nói, và ≥ 0,6 s câu bot đã đến hạn vọng về. Cuộc gọi kiểm lại: đủ chữ.

## 10. Câu trả lời ngắn khi bot đang nói

Cuộc gọi outbound 08/10: "OK" -> "OK EM" (SNR 36 dB) không ngắt được bot — gate đòi validator ACCEPT,
tức hai partial liên tiếp giống nhau >= 60% ("ok" / "ok em" = 57%); câu ngắn hết trước khi có đủ.
Giờ câu <= 3 từ gồm từ trả lời/lệnh (`validator.is_short_answer`) qua được khi đủ dài/to/chắc; kiểm
tra echo vẫn chạy trước. `later_run.py` (điện thoại, "later"): echo_only −30/−20 dB lượt giả 0/12,
bot tự ngắt lời 0/12; người gọi như §1 (xác nhận 14/20, mất chữ 0,145). Rủi ro còn lại: người bên
cạnh nói câu ngắn kiểu "À CHỊ KHÔNG" cũng ngắt được bot (cùng gốc với R2).

## 9. Cổng giọng người gọi theo đoạn con

Cuộc gọi 08/10 (enforce bản cũ, so cả lượt): lượt dài đầu tiên 13,9 s là tin tức từ điện thoại phát
gần mic lẫn "Alo tôi tên là…" → thành giọng mẫu → lượt thật của người gọi similarity 0,12 bị chặn,
bot nghe im lặng 3 lần rồi chuyển máy. Bản mới (`speaker_gate.py`): đoạn 1,5 s; giọng mẫu chỉ khi mọi
cặp đoạn giống nhau >= 0,3; chặn khi trung bình < 0,15 và không đoạn nào >= 0,22; cắt đầu/cuối chỉ
khi đoạn đó < 0,10 và phần còn lại >= 0,22 (pipeline decode lại phần giữ).

Phân bố similarity đoạn 1,5 s với giọng mẫu cùng người (người gọi = bộ web, người khác = VIVOS):

| Model | Đoạn người gọi p2 / p5 / p10 | Đoạn người khác p95 / p99 | Thời gian |
|---|---|---|---|
| TitaNet-small (cũ) | 0,04 / 0,10 / 0,16 | 0,22 / 0,31 | ~97 ms |
| **CAM++ zh_en (chọn)** | 0,18 / 0,26 / 0,32 | 0,21 / 0,27 | ~127 ms |
| ERes2NetV2 | 0,22 / 0,26 / 0,31 | 0,22 / 0,29 | ~472 ms (chậm) |
| WeSpeaker ResNet34 | 0,44 / 0,50 / 0,56 | 0,57 / 0,65 | — (kém) |

Mô phỏng cuộc gọi (scratch `gate_eval.py`, 12 cuộc, CAM++): lượt đầu lẫn giọng khác không thành
giọng mẫu 12/12; câu người gọi 0/27 bị chặn hay cắt; câu chỉ người khác bị chặn 29/36; người khác rồi
người gọi trong một lượt: cắt đúng 14/36, giữ nguyên 17, cắt lệch 4, chặn cả lượt 1. Cắt theo đoạn
1,5 s còn thô — vì vậy chạy `log` trước trên cuộc gọi thật.

Cuộc gọi thật ở chế độ log (điện thoại phát TikTok cạnh mic laptop): giọng mẫu lấy đúng từ "Ờ ANH TÊN
LÀ NGUYỄN VĂN A NHỈ" (3 đoạn, cặp >= 0,46); đoạn của người gọi 0,54-0,74; lượt "DỄ NGHE TIKTO… | EM CÓ
THỂ HỖ TRỢ…" có đoạn 0,15 / 0,12 | 0,67 / 0,60 — ngưỡng cắt 0,10 (đặt theo dữ liệu khác cuộc gọi) quá
thấp; "BẰNG QUY NHÁ" (1,6 s, điện thoại) không được chấm vì < 2 s. Chỉnh: đoạn < 0,25 là giọng khác
(cắt đầu/cuối khi phần còn lại >= 0,35; chặn khi trung bình < 0,25 và không đoạn nào >= 0,35); đã có
giọng mẫu thì chấm cả lượt >= 1 s (một đoạn: chặn khi < 0,2). Mô phỏng lại (khác cuộc gọi — xấu
nhất): câu chỉ người khác bị chặn 36/36; người khác rồi người gọi cắt đúng 21/36 (chặn cả lượt 3);
người gọi rồi người khác cắt đúng 22/36; câu người gọi cắt nhầm 2/27, chặn nhầm 0. Bật `enforce`
theo yêu cầu owner. Chưa làm: dùng cổng để chặn người khác ngắt lời bot.

## Còn mở

- **Người/TV/điện thoại phát gần mic (R2):** cổng theo đoạn con (§9) ở chế độ log; giọng nói chồng
  lên nhau cùng lúc thì không tách được ở tầng này.
- **Người nói xa (R3):** Silero phụ thuộc mức âm tuyệt đối (−53 dBFS: 7/13 câu golden không thành
  lượt); gain theo mức giọng của từng cuộc gọi chỉ cho bản sao vào VAD đã thử offline, chưa tích hợp.
- `turn_min_speech_ms`/`post_bot_guard_ms` so thời gian trôi chứ không phải thời lượng tiếng nói nên
  không chặn được gì với Silero + ZipFormer; khử echo phía server (AEC3 của LiveKit) chỉ phù hợp SIP
  và phải bật sau khi đo thấy vọng (không vọng thì mất chữ 0,067 → 0,617).

## Kiểm chứng

| Lệnh | Kết quả |
|---|---|
| `ruff check` / `ruff format --check` (src, tests, eval/noise-bench) | Pass |
| `STT_EVAL_ENABLED=false PYTHONPATH=src python -m pytest -q` | 5029 passed, 9 skipped |
| `scripts/export_openapi.py --check` | Pass |
| Test mới chạy trên `src` của mốc | 6/8 test của `test_bot_starts_mid_utterance.py` thất bại (tái hiện đúng lỗi) |
| noise-bench `r3b_*` (cấu hình cuối) so với `ucbase_*` | Như bảng §2; golden-web sạch giống hệt |
