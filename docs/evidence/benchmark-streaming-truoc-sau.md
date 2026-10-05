# Benchmark: trước / sau Vbee streaming

## Mục tiêu

Đo cùng một bộ benchmark trước và sau khi merge nhánh `feature/tts-w3-vbee-streaming` để biết streaming thay đổi gì trên prod:
- Đường B (LiveKit): E2E latency, tức khách chờ bao lâu mới nghe tiếng bot.
- Đường A (HTTP chấm điểm): có bị ảnh hưởng không.
- TTS từng độ dài câu: TTFA giảm bao nhiêu.

Cách đo, thuật ngữ (TTFA, E2E, Stall…) và quota: [latency-benchmark.md](../reference/latency-benchmark.md). Script: `scripts/bench/`.

| | Trước | Sau |
|---|---|---|
| Ngày chạy | 02/10/2026, ~01:37 giờ VN | 05/10/2026, ~11:02 giờ VN (`sau-2`: ~11:08) |
| Image | `9344380` (main, Vbee chưa stream) | `97e139c` (main sau PR #70 TTS, kèm PR #71 audio stack và #68 dialogue variants) |
| Lệnh | `bash bench/run.sh truoc` (profile `quick`, lịch `apt_00427`) | `bash bench/run.sh sau`, rồi `bash bench/run.sh sau-2 --parts livekit` |
| Kết quả thô | `result/05-10-2026/bench/truoc/` (và `thu/`) | `result/05-10-2026/bench/sau/`, `sau-2/` |
| Quota (ký tự Vbee của bot) | ~1.900 (cộng ~400 của lần chạy thử `thu`) | ~2.130 (gồm `sau-2`) |

## Kết quả TRƯỚC

### Phần 1 — TTS tại `SpeechSynthesizer` (container `livekit-worker`)

`stream=False`: bản cũ chờ Vbee trả đủ câu rồi mới đưa một khối, nên TTFA = TTS total.

| Câu | Ký tự | n | TTFA p50 (min–max) ms | TTS total p50 ms | RTF | Stall ms |
|---|---|---|---|---|---|---|
| ngắn | 45 | 3 | 242 (185–249) | 242 | 11,2 | 0 |
| vừa | 113 | 3 | 576 (355–605) | 576 | 12,4 | 0 |
| dài | 234 | 3 | 1063 (1009–1122) | 1063 | 13,4 | 0 |

### Phần 2 — HTTP như harness (container `bot` → Caddy, 1 cuộc gọi)

| Lượt | Response ms | Tải audio ms | Turn latency ms | Ký tự bot |
|---|---|---|---|---|
| mở phiên | 1498 | 13 | 1511 | 112 |
| lượt 1 | 5366 | 13 | 5379 | 110 |
| lượt 2 | 940 | 4 | 944 | 110 |

Lượt ≥ 8 s: 0 · WAV sai: 0 · lỗi: 0.

Trace phía server (p50 của 3 lượt): Turn 1345 · STT 2247 · Engine 206 · **TTS total 749 · TTFA Vbee 442** ms.

### Phần 3 — Cuộc gọi LiveKit, đo phía người gọi (1 cuộc gọi)

| Lượt | n | E2E latency p50 | STT (endpointing + ASR) p50 | Engine p50 | **TTFA p50 (Engine trả câu → có tiếng)** | Ký tự bot |
|---|---|---|---|---|---|---|
| câu chào* | 1 | 1867 | – | 1019 | **848** | 112 |
| lượt | 2 | 2268 | 1327 | 32 | **909** | 110 |

\*Câu chào: E2E tính từ lúc vào phòng; cột "Engine" của câu chào gồm cả dispatch worker và gọi Clinic.

Lỗi: 0 · lượt ASR không ra chữ: 0. Trace worker: TTFA Vbee 561 ms (p50). Trên bản này bot vẫn phải chờ đủ câu mới phát, nên con số này **không phải** lúc khách nghe tiếng.

**Lần chạy thử `thu`** (cùng image, 1 cuộc gọi, 5 phút trước): câu chào TTFA 1066 ms; các lượt E2E 2342 · STT 1318 · Engine 36 · **TTFA 988** ms. Dùng làm mẫu "trước" thứ hai để ước độ nhiễu.

## Nhận xét về số trước

- **Đường B, E2E latency ~2,3 s mỗi lượt:**
  - STT ~1,3 s, phần lớn nhất. Gồm thời gian VAD chờ im lặng để chốt lượt cộng ASR, không thuộc TTS.
  - TTFA ~0,9 s.
  - Engine ~30 ms.
  - Streaming chỉ tác động vào phần TTFA.
- **Cần xem ở lần "sau":** TTFA của phần 3 có giảm không và giảm bao nhiêu. Không đặt trước con số; chỉ kết luận từ số đo "sau". STT và Engine không đổi. Ở phần 1, TTFA phải tách khỏi TTS total (nhiều chunk), còn TTS total giữ nguyên hoặc nhỉnh hơn một chút.
- **Đường A không đổi theo streaming:** vẫn gom cả câu; TTS total ~0,75 s mỗi lượt.
- **Lượt 1 của HTTP mất 5,4 s:** gần như chắc chắn **không do TTS** (TTS total chỉ ~0,75 s), mà do STT (trung vị STT 2,2 s). Cần xem từng lượt trong `bench-results/truoc/http_traces.json`. Nếu đúng là STT chậm ở lượt đầu thì báo Việt. Vẫn trong trần 8 s.
- **Độ nhiễu:** giữa `thu` và `truoc` (cùng image, cách nhau 5 phút), TTFA lệch ~80 ms ở các lượt và ~220 ms ở câu chào. Với 1 cuộc gọi mỗi lần, **chênh dưới ~150 ms giữa trước và sau thì chưa kết luận được**.
- **Tốc độ sinh:** RTF 11–13, tức Vbee sinh nhanh hơn tốc độ phát hơn 10 lần, nên khi stream sẽ không bị giật. Thời gian TTS tăng ~4–5 ms mỗi ký tự.

## Kết quả SAU

Phần 1 in `stream=True`, tức bản đang chạy là bản stream. Cả hai lần chạy: lỗi 0, fallback 0.

### Phần 1 — TTS tại `SpeechSynthesizer` (container `livekit-worker`)

| Câu | Ký tự | n | TTFA p50 (min–max) ms | TTS total p50 ms | RTF | Stall ms | Chunk |
|---|---|---|---|---|---|---|---|
| ngắn | 45 | 3 | 250 (242–263) | 252 | 10,7 | 0 | 20 |
| vừa | 113 | 3 | 445 (273–792) | 588 | 12,2 | 0 | 51 |
| dài | 234 | 3 | 268 (254–432) | 1010 | 14,1 | 0 | 101 |

### Phần 2 — HTTP như harness (1 cuộc gọi)

| Lượt | Response ms | Tải audio ms | Turn latency ms | Ký tự bot |
|---|---|---|---|---|
| mở phiên | 1538 | 13 | 1550 | 91 |
| lượt 1 | 1248 | 5 | 1254 | 110 |
| lượt 2 | 891 | 5 | 896 | 110 |

Lượt ≥ 8 s: 0 · WAV sai: 0 · lỗi: 0.

Trace phía server (p50 của 3 lượt): Turn 1240 · STT 228 · Engine 546 · **TTS total 708 · TTFA Vbee 468** ms.

### Phần 3 — Cuộc gọi LiveKit (2 cuộc gọi: `sau`, `sau-2`)

| Lần | Lượt | n | E2E latency p50 | STT p50 | Engine p50 | **TTFA p50** | Ký tự bot |
|---|---|---|---|---|---|---|---|
| `sau` | câu chào | 1 | 5347 | – | 4116 | **1232** | 92 |
| `sau` | lượt | 2 | 3038 | 2204 | 112 | **721** | 110 |
| `sau-2` | câu chào | 1 | 2193 | – | 1164 | **1029** | 112 |
| `sau-2` | lượt | 2 | 2083 | 1388 | 120 | **574** | 87 |

Lỗi: 0 · lượt ASR không ra chữ: 0. Câu bot đổi độ dài (92, 87 ký tự) vì PR #68 thêm biến thể câu thoại.

## So sánh

### Phần 1 và 2 (`compare.py truoc sau`)

| Chỉ số (ms) | Trước | Sau | Chênh |
|---|---|---|---|
| Ngắn 45 ký tự: TTFA p50 | 242 | 250 | +9 |
| Vừa 113 ký tự: TTFA p50 | 576 | 445 | −131 |
| **Dài 234 ký tự: TTFA p50** | **1063** | **268** | **−796** |
| Ngắn / vừa / dài: TTS total p50 | 242 / 576 / 1063 | 252 / 588 / 1010 | +11 / +12 / −54 |
| Stall (cả 3 câu) | 0 | 0 | 0 |
| Đường A: Turn latency p50 | 1511 | 1254 | −258 |
| Đường A: Turn latency max | 5379 | 1550 | −3828 |
| Đường A, trace: TTS total p50 | 749 | 708 | −42 |
| Đường A, trace: TTFA Vbee p50 | 442 | 468 | +25 |
| Đường A, trace: STT p50 | 2247 | 228 | −2018 |

### Phần 3: từng lượt của 4 cuộc gọi

Mỗi lần chỉ 1 cuộc gọi, nên bảng ghi từng lượt thay vì p50. Cột cuối lấy từ trace của worker.

| Lần | Lượt | E2E | STT | Engine | **TTFA** (Engine trả câu → có tiếng) | Ký tự bot | TTFA Vbee (trace) | TTFA − TTFA Vbee |
|---|---|---|---|---|---|---|---|---|
| `thu` (trước) | câu chào | 2055 | – | 989 | 1066 | 112 | 678 | 388 |
| `thu` (trước) | lượt 1 | 2327 | 1303 | 32 | 992 | 110 | 589 | 403 |
| `thu` (trước) | lượt 2 | 2358 | 1334 | 41 | 983 | 110 | 610 | 373 |
| `truoc` | câu chào | 1867 | – | 1019 | 848 | 112 | 482 | 366 |
| `truoc` | lượt 1 | 2234 | 1318 | 31 | 885 | 110 | 561 | 324 |
| `truoc` | lượt 2 | 2303 | 1336 | 34 | 933 | 110 | 566 | 367 |
| `sau` | câu chào | 5347 | – | 4116 | 1232 | 92 | 1001 | 231 |
| `sau` | lượt 1 | 4008 | 3131 | 179 | 698 | 110 | 565 | 133 |
| `sau` | lượt 2 | 2068 | 1278 | 45 | 744 | 110 | 608 | 136 |
| `sau-2` | câu chào | 2193 | – | 1164 | 1029 | 112 | 895 | 134 |
| `sau-2` | lượt 1 | 2223 | 1416 | 211 | 595 | 87 | 478 | 117 |
| `sau-2` | lượt 2 | 1943 | 1361 | 29 | 553 | 87 | 417 | 136 |

**TTFA − TTFA Vbee** là khoảng từ lúc byte đầu của Vbee về server tới lúc phía người gọi nghe tiếng. Đây là phần streaming bỏ đi (trước: chờ Vbee sinh xong cả câu). Cột này không phụ thuộc Vbee nhanh hay chậm ở lần đó, nên so được dù chỉ có ít mẫu. Hai cột được đo bằng hai đồng hồ khác nhau (người gọi, worker), nên chỉ dùng để so trước/sau, không coi là số tuyệt đối.

**Câu chào: thời gian tạo client async.** Đo trong container `livekit-worker` trên EC2 (3 lần, `GET https://api.vbee.vn/` không token, không tốn quota): tạo `httpx.AsyncClient` mất 39–74 ms, request đầu trên kết nối mới 47–115 ms, request thứ hai trên cùng kết nối 5–7 ms. Bản mới tạo client này ở lần stream đầu tiên của job, tức lúc đọc câu chào; các lượt sau dùng lại kết nối. Bản cũ tạo client và kết nối mới cho mọi câu.

## Kết luận

1. **Streaming chạy đúng trên prod.** `stream=True`, không lỗi, không fallback, Stall 0 ở cả 3 độ dài câu. TTS total không đổi, chỉ TTFA giảm.
2. **Tại `SpeechSynthesizer`, câu càng dài càng lợi.** Câu dài 234 ký tự: TTFA 1063 → 268 ms; khoảng min–max của trước và sau không chồng nhau. Câu vừa 576 → 445 ms, nhưng một lần Vbee trả byte đầu chậm (792 ms) nên dao động lớn. Câu ngắn không đổi (242 → 250 ms), vì Vbee sinh xong gần như cùng lúc với chunk đầu.
3. **Trên cuộc gọi LiveKit, các lượt nhanh hơn.**
   - TTFA của 4 lượt sau: 553–744 ms. 4 lượt trước: 885–992 ms.
   - Hai lượt cùng độ dài 110 ký tự (`sau`): 698 và 744 ms, so với 885–992 ms trước đó.
   - Khoảng từ byte đầu của Vbee tới lúc nghe tiếng giảm từ 324–403 ms xuống 117–136 ms ở cả 4 lượt. Đây là phần streaming bỏ đi.
4. **Câu chào chưa nhanh hơn.** TTFA trước 848 / 1066 ms, sau 1232 / 1029 ms.
   - Streaming vẫn có tác dụng: khoảng từ byte đầu tới lúc nghe giảm từ 366 / 388 xuống 231 / 134 ms.
   - Nhưng byte đầu của Vbee cho câu chào về chậm hơn ở cả hai lần sau (1001 / 895 ms, trước 482 / 678 ms). Các lượt sau câu chào thì không chậm (417–608 ms, trước 561–610 ms).
   - **Chưa rõ nguyên nhân**, mới có 2 mẫu mỗi bên. Không phải do tạo client: bản cũ tạo `httpx.Client` mới và mở kết nối mới cho mọi câu, kể cả câu chào, nên chi phí này có ở cả hai bên.
   - Bản mới vẫn tạo client async và mở kết nối Vbee ngay trên đường câu chào (lần stream đầu của job). Đo được tốn khoảng 90–190 ms (mục trên). Nếu muốn bỏ phần này thì tạo sẵn client và mở kết nối lúc job bắt đầu (chưa làm).
   - Theo dõi tiếp TTFA câu chào bằng trace các cuộc gọi tuần 4.
5. **Đường A (HTTP chấm điểm) không đổi theo streaming.** TTS total 749 → 708 ms, TTFA Vbee 442 → 468 ms; không lượt nào ≥ 8 s.
6. **E2E không dùng để đánh giá streaming lần này.** Image sau có thêm PR #71 (ASR pipeline, audio input) và #68 (biến thể câu thoại), nên STT, Engine và số ký tự bot đổi vì lý do khác.
   - Lần `sau` có STT lượt 1 3131 ms và Engine câu chào 4116 ms. Lần `sau-2` 5 phút sau không lặp lại (STT 1361–1416, Engine câu chào 1164), nên chưa coi là lỗi.
   - Ở `sau-2`, STT ngang trước (~1,4 s) và E2E các lượt là 1943–2223 ms, so với 2234–2358 ms trước đó.
   - Lượt 1 HTTP trước đây mất 5,4 s do STT 4353 ms; lần sau STT lượt đó còn 315 ms (1 mẫu, nhiều khả năng nhờ PR #71).

## Cách đã chạy "sau"

1. Kiểm `grep IMAGE /opt/callbot/image.env` ra `97e139c` (CD deploy xong).
2. Chép lại `scripts/bench/` lên EC2 (chỉ đổi tên cột trong `compare.py`, cách đo giữ nguyên).
3. `bash bench/run.sh sau --dry-run`, rồi `bash bench/run.sh sau`.
4. Chênh TTFA các lượt ở lần `sau` gần ngưỡng nhiễu, nên chạy thêm `bash bench/run.sh sau-2 --parts livekit`.
5. `python3 bench/compare.py bench-results/truoc bench-results/sau`, rồi tải cả thư mục `bench-results` về `result/05-10-2026/bench/` (không chứa text hội thoại).

## Ghi chú

- Số mẫu nhỏ (1 cuộc gọi, 2 lượt mỗi lần chạy) vì quota. Mức nhiễu giữa hai lần cùng image (`thu`, `truoc`) là ~80 ms ở các lượt và ~220 ms ở câu chào.
- Lần "trước" chạy ~01:37, lần "sau" ~11:02 giờ VN. Tải của Vbee có thể khác theo giờ; đây là một lý do nên so cột "TTFA − TTFA Vbee" thay vì chỉ so TTFA.
- Mốc "bot có tiếng" (dùng cho TTFA và E2E) của phần 3 gồm cả đoạn lặng đầu câu của Vbee và độ trễ mạng LiveKit. Các phần này như nhau giữa các lần chạy, nên **chênh lệch** là số đúng, còn giá trị tuyệt đối hơi cao hơn lúc khách thực sự nghe.
- `livekit_call.py` in `AssertionError` trong `FfiHandle.__del__` lúc thoát. Lỗi này của thư viện LiveKit khi process người gọi giả kết thúc, không thuộc bot, không ảnh hưởng số đo.

## Đọc các cột thế nào

Một lượt trên cuộc gọi LiveKit đi qua các mốc sau. Mỗi cột trong bảng là một đoạn trên đường này:

```text
khách nói xong ──STT──> bot chốt lượt ──Engine──> có câu trả lời ──TTFA──> khách nghe tiếng bot
└──────────────────────────────── E2E latency ─────────────────────────────────┘
                                                  └────────── TTS total ──────────> bot sinh xong câu
```

| Cột | Nghĩa | Tên cũ (trong `summary.md` lần `truoc` trên EC2) |
|---|---|---|
| **E2E latency** | Từ lúc khách nói xong tới lúc nghe tiếng bot. Đây là con số khách cảm nhận | Khách nói xong → bot có tiếng |
| **STT (endpointing + ASR)** | Từ lúc khách nói xong tới lúc bot chốt lượt: VAD chờ đủ khoảng im lặng, rồi ASR ra chữ | STT (→ bot chốt lượt) |
| **Engine** | Từ lúc có chữ tới lúc có câu trả lời (luật hội thoại, LLM, Clinic) | Engine |
| **TTFA** (time to first audio) | Từ lúc có câu trả lời tới lúc có âm thanh đầu tiên. Đây là phần streaming tác động | Âm đầu; TTS (Engine trả câu → có tiếng) |
| **TTS total** | Từ lúc gọi TTS tới lúc sinh xong cả câu. Đường A (HTTP chấm điểm) phải chờ hết đoạn này | Xong câu; TTS cả câu |
| **TTFA Vbee** | Lúc byte audio đầu tiên của Vbee về tới server (đọc từ trace). Chưa phải lúc khách nghe | TTS byte đầu |
| **Turn latency** | Đường A: response + tải `audio_url`, đúng cách harness tính, trần 8 s (§4.1.2) | Tổng mỗi lượt |
| **RTF** (real-time factor) | Thời lượng audio / TTS total. Ví dụ 12 nghĩa là sinh nhanh gấp 12 lần tốc độ phát | RTF |
| **Stall** | Tổng thời gian bot phải ngừng giữa câu để chờ audio về (giật). 0 là phát liền | Giật |
| **Barge-in stop latency** | Từ lúc khách bắt đầu nói chen tới lúc bot im | Nói chen → bot im |
| **Cancel** | Bot gọi hủy TTS giữa câu: bao lâu thì stream dừng | Hủy giữa câu |
| **Fallback** | Vbee lỗi, ElevenLabs đọc thay: TTFA trong trường hợp này | Vbee hỏng → dự phòng |
| **p50 / p95** | p50 = trung vị (một nửa số lượt nhanh hơn). p95 = 95% số lượt nhanh hơn. p95 chỉ hiện khi có từ 10 mẫu trở lên, ít hơn thì để "–" | Trung vị |

Ví dụ với số trước: E2E ~2,3 s = STT ~1,3 s + Engine ~0,03 s + TTFA ~0,9 s. Streaming chỉ làm giảm TTFA. Muốn E2E giảm nhiều hơn thì phải giảm STT, việc của bên STT.

Chi tiết cách đo: [latency-benchmark.md](../reference/latency-benchmark.md).
