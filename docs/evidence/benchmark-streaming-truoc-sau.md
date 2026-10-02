# Benchmark: trước / sau Vbee streaming

## Mục tiêu

Đo cùng một bộ benchmark trước và sau khi merge nhánh `feature/tts-w3-vbee-streaming` để biết streaming thay đổi gì trên prod:
- Đường B (LiveKit): E2E latency, tức khách chờ bao lâu mới nghe tiếng bot.
- Đường A (HTTP chấm điểm): có bị ảnh hưởng không.
- TTS từng độ dài câu: TTFA giảm bao nhiêu.

Cách đo, thuật ngữ (TTFA, E2E, Stall…) và quota: [latency-benchmark.md](../reference/latency-benchmark.md). Script: `scripts/bench/`.

| | Trước | Sau |
|---|---|---|
| Ngày chạy | 02/10/2026, ~01:37 giờ VN | _(điền sau)_ |
| Image | `9344380` (main, Vbee chưa stream) | _(điền sau)_ |
| Lệnh | `bash bench/run.sh truoc` (profile `quick`, lịch `apt_00427`) | `bash bench/run.sh sau` |
| Kết quả thô trên EC2 | `/opt/callbot/bench-results/truoc/` | `/opt/callbot/bench-results/sau/` |
| Quota | ~1.900 ký tự Vbee (cộng ~400 ký tự của lần chạy thử `thu`) | ~1.950 (sinh lại câu người gọi) |

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

## Kết quả SAU _(điền sau khi merge + deploy)_

### Phần 1 — TTS

| Câu | Ký tự | n | TTFA p50 (min–max) ms | TTS total p50 ms | RTF | Stall ms | Chunk |
|---|---|---|---|---|---|---|---|
| ngắn | 45 | | | | | | |
| vừa | 113 | | | | | | |
| dài | 234 | | | | | | |

### Phần 2 — HTTP

| Lượt | Response ms | Tải audio ms | Turn latency ms | Ký tự bot |
|---|---|---|---|---|
| mở phiên | | | | |
| lượt 1 | | | | |
| lượt 2 | | | | |

Trace server (p50): Turn · STT · Engine · TTS total · TTFA Vbee:

### Phần 3 — LiveKit

| Lượt | n | E2E latency p50 | STT (endpointing + ASR) p50 | Engine p50 | TTFA p50 (Engine trả câu → có tiếng) | Ký tự bot |
|---|---|---|---|---|---|---|
| câu chào | | | – | | | |
| lượt | | | | | | |

## So sánh _(điền sau)_

Chạy trên EC2 rồi dán bảng vào đây:

```bash
python3 bench/compare.py bench-results/truoc bench-results/sau > bench-results/so-sanh.md
```

Kết luận: _(điền sau)_

## Việc cần làm khi chạy "sau"

1. Merge PR, đợi CD deploy xong. Kiểm `grep IMAGE /opt/callbot/image.env` ra commit mới.
2. Nếu đã sửa `scripts/bench/` từ lần trước thì chép lại lên EC2. Nếu không sửa thì giữ nguyên, để hai lần đo dùng cùng script.
3. Chạy ở khung giờ tương tự và khi không có cuộc gọi nào khác. Dùng **cùng profile `quick` và cùng lịch `apt_00427`**:
   ```bash
   cd /opt/callbot
   bash bench/run.sh sau --dry-run
   bash bench/run.sh sau
   ```
   Nếu mở phiên lỗi `OUTBOUND_START_FAILED` thì thêm `--appointment apt_00426` và ghi lại ở đây.
4. Chạy `compare.py`, điền các bảng ở trên, viết kết luận.
5. Lưu kết quả thô vào repo để không phụ thuộc EC2. Kết quả không chứa text hội thoại.
   ```powershell
   scp -i $env:USERPROFILE\.ssh\vmec-bot.pem -r ubuntu@vmec-callbot.tech:/opt/callbot/bench-results result/02-10-2026/bench
   ```

## Ghi chú

- Số mẫu nhỏ (1 cuộc gọi, 2 lượt mỗi lần chạy) vì quota. Nếu chênh trước/sau nằm trong mức nhiễu (~150 ms), có thể chạy thêm `bash bench/run.sh sau-2 --parts livekit` (~400 ký tự) để có thêm mẫu "sau". Mẫu "trước" thì đã có 2 lần (`thu`, `truoc`).
- Mốc "bot có tiếng" (dùng cho TTFA và E2E) của phần 3 gồm cả đoạn lặng đầu câu của Vbee và độ trễ mạng LiveKit. Các phần này như nhau giữa hai lần chạy, nên **chênh lệch** là số đúng, còn giá trị tuyệt đối hơi cao hơn lúc khách thực sự nghe.

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
