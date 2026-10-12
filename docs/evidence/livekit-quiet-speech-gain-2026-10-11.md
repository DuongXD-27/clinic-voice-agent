# Evidence: Giọng người gọi quá nhỏ trên LiveKit — tăng âm có điều kiện — 11/10/2026

Phạm vi: đường LiveKit (web và SIP), phần trước VAD/ASR (`speech/audio/quiet_gain.py`,
`STTPipeline._fanout`). Không đổi VAD, ASR, chốt lượt.

## Hiện trạng và điểm yếu

| Đường | Xử lý âm lượng hiện có |
|---|---|
| Web (`/ui/livekit`) | AGC của trình duyệt (`livekit-client` mặc định `autoGainControl: true`) |
| SIP (điện thoại) | **Không có gì** — đánh giá 30/09 đã đề xuất AGC cho đường này "khi làm", đường SIP nay đã chạy |
| Server | Không có |

**Silero phụ thuộc mức âm tuyệt đối.** Đo 11/10 (`silero_level` trong thư mục tạm của phiên, giọng
web và golden trên nền gần im lặng, tỉ lệ frame tiếng nói còn nhận ra so với ở −20 dBFS):

| Mức giọng (RMS vùng có giọng) | −20 | −30 | −35 | −40 | −45 | −50 | −55 dBFS |
|---|---|---|---|---|---|---|---|
| Giọng web (16 kHz) | 0,998 | 0,954 | 0,901 | 0,880 | 0,778 | **0,418** | **0,170** |
| Giọng golden (8 kHz điện thoại) | 0,988 | 0,846 | 0,856 | 0,810 | 0,716 | 0,646 | 0,431 |

Nhiễu văn phòng thuần (cắt từ dump thật, mức = RMS cả đoạn 10 s, kênh web): Silero **không báo nhầm
frame nào tới −45 dBFS**, báo nhầm ~2% frame từ −40 dBFS. Tức có một vùng an toàn: tăng giọng nhỏ lên
trong khi nền nhiễu vẫn ≤ −50 dBFS (kênh điện thoại thì khác — mục "Kênh điện thoại").

**Mức âm cuộc gọi thật** (234 dump `temp/audio/livekit_debug_web-*.wav` ≥ 8 s, Silero gắn cờ): mức
giọng (p90 frame có giọng) trung vị −20,4 dBFS, 5% cuộc gọi dưới −33,7 dBFS; nền nhiễu trung vị
−82,5 dBFS (khử nhiễu trình duyệt thường đưa về im lặng số). Đoạn Silero gắn cờ mà nhỏ (p90 < −40
dBFS): 146/1272. Đối chiếu log các cuộc gọi nhỏ nhất: phần lớn đoạn nhỏ là **TV / người nói phía
sau** ("THANH THỦY ĐÂY LÀ SÓNG TRUYỀN HÌNH TRỰC TIẾP…", "TÔI ĐÃ XONG CÁC BẠN XIN CÁM ƠN…") chứ không
phải người gọi — tăng âm theo "mức tiếng nói gần đây" sẽ kéo cả TV lên thành lượt giả.

Chiều ngược lại (giọng quá to, cắt đỉnh) không phải điểm yếu hiện tại: trong 245 dump, đỉnh chạm gần
full scale là thường (trung vị −0,9 dBFS) nhưng không cuộc gọi nào có quá 0,01% mẫu bị cắt đỉnh (tệ
nhất 0,008%).

**Silero "nhớ" mức âm.** Trong một cuộc gọi, trạng thái của Silero mang theo mức âm đã nghe: sau
một câu to hơn, câu kế tiếp nhỏ hơn bị nhận trễ hoặc bỏ sót, dù vẫn đủ to. Đo trên một đoạn cuộc
gọi web (3 câu, câu giữa được nhân thêm hệ số, câu cuối −26 dBFS):

| Câu giữa to hơn | +3 dB | +6 dB | +10 dB | +14 dB |
|---|---|---|---|---|
| Câu cuối bắt đầu được nhận ra trễ | 0,03 s | 0,30 s | **1,86 s** | **cả 3 s không nhận ra** |

Nhân cả cuộc gọi một hệ số không đổi thì không sao — chỉ sự **thay đổi** mức giữa các câu gây hại.
Đây là điểm yếu âm lượng có sẵn (người gọi lúc to lúc nhỏ, tiếng ho/đập bàn to), và là cái bẫy của
mọi AGC thay đổi hệ số theo thời gian: lần đo đầu của bộ tăng âm (hệ số rơi 14 dB giữa câu khi người
gọi nói to lên) làm câu sau mất 1,9 s đầu.

**Đã thử và loại — xoá trạng thái Silero sau 0,5–1 s im lặng.** Trên ca câu to → câu nhỏ, xoá trạng
thái làm câu sau nhận đúng lúc. Nhưng Silero cũng thích nghi với im lặng nên nhạy hơn với giọng nhỏ;
xoá trạng thái mất luôn điều đó. Trên 37 trial golden (2 câu khởi động + câu đo, chỉ chạy Silero):

| Câu đo | Không xoá | Xoá sau 1 s | Xoá + mồi lại 1 s nền | Xoá + mồi lại 2 s nền |
|---|---|---|---|---|
| Mức thường | 0,497 · mất 0 | 0,503 · 0 | 0,521 · 0 | 0,495 · 0 |
| −15 dB | **0,480 · 0** | 0,327 · 4 | 0,331 · 3 | 0,364 · 2 |
| −25 dB | **0,624 · 1** | 0,401 · 4 | 0,451 · 5 | 0,438 · 3 |
| Câu khởi động to hơn 12 dB, câu đo −15 dB | **0,381 · 4** | 0,315 · 4 | 0,335 · 4 | 0,344 · 5 |

(tỉ lệ frame có giọng được nhận ra · số câu không nhận ra frame nào). Qua cả pipeline (golden sạch
−15 dB): WER lượt 0,207 → 0,373, mất lượt 1 → 5. **Đã gỡ code**, chỉ giữ số đo. Bộ tăng âm thay vào
đó không giảm hệ số giữa các câu (mục Sửa).

**Đã thử trước đây (không làm lại):**
- AGC server cho web (30/09, nhánh `fix/livekit-turn-loss`): ở mức thường WER lượt 0,095 → 0,179
  (WebRTC) / 0,259 (Speex) vì trình duyệt đã chỉnh mức; chỉ có ích khi giọng nhỏ hơn 25 dB.
- Lọc "giọng người gọi" theo mức năng lượng (25/09): chênh lệch người gọi / người xung quanh trung
  vị chỉ 3,2 dB, có cuộc gọi người xung quanh to hơn — đã gỡ.
- Hạ ngưỡng Silero 0,5 → 0,4 / 0,3 (25/09): thêm 1–4 điểm nhận ra nhưng báo nhầm tăng 2–3 lần.

## Sửa: tăng âm có điều kiện (`QuietSpeechGain`)

Một hệ số cho cả luồng của cuộc gọi, áp lên frame trước mọi bước (bộ phân loại dùng chung, VAD,
ASR, bằng chứng SNR, tiếng vọng) trong `STTPipeline._fanout`. Cùng ngưỡng với khuếch đại tĩnh của
đường HTTP (`normalize_gain`, đã đo 30/09: cứu clip nhỏ, không hại clip thường):

- **Giọng đủ to (≥ −35 dBFS): hệ số 0 dB, luồng giữ nguyên từng byte** — không lặp lại lỗi AGC
  server ở mức thường.
- Giọng nhỏ: đưa về −26 dBFS, tối đa +20 dB, có đoạn chuyển 5 dB dưới ngưỡng (không nhảy 0 → +9 dB).
- **Nền nhiễu sau khi tăng không vượt −50 dBFS**, nền = phân vị 90 mức các frame không có tiếng nói
  trong ~10 s (gồm cả lúc bot nói, nên tiếng vọng còn sót cũng làm giảm hệ số): phòng ồn / TV / tiếng
  vọng càng to thì càng ít tăng — tăng âm không cải thiện SNR, nền đã to thì tăng chỉ thêm báo nhầm.
  Phân vị 90 vì nhiễu thật đến từng cụm và đỉnh cụm mới làm Silero báo nhầm (mục kế tiếp); không
  dùng RMS vì một tiếng gõ / va chạm máy ngắn đủ kéo RMS lên và hệ số tụt giữa cuộc gọi.
- **Mức giọng = đoạn nói to nhất gần đây, giảm 3 dB/phút**: chỉ tăng khi mọi giọng nghe được đều
  nhỏ. Người gọi nói bình thường rồi im, TV nói nhỏ phía sau → không tăng. Không tính lúc bot nói và
  0,5 s ngay sau đó (tiếng vọng, dư âm — mục "Cuộc gọi web thật"), không tính đoạn ngắn hơn 0,3 s
  (tiếng gõ, ho).
- **Hệ số chỉ đổi sau 1 s im lặng liên tục** (giữ nguyên trong cả câu) và **không giảm chỉ vì người
  gọi nói to hơn** (tránh "trí nhớ mức âm" của Silero); chỉ giảm khi nền nhiễu lên hoặc giọng sau khi
  tăng đã quá −12 dBFS.
- Đỉnh mẫu sau khi tăng ≤ −1 dBFS.
- Log `quiet_gain: gain=… speech=… floor=…` khi hệ số đổi ≥ 3 dB.

Cờ: `quiet_speech_gain_enabled` (config/speech.yaml): **bật cho cuộc gọi web, tắt cho cuộc gọi SIP**
(`phone_overrides`, lý do ở mục "Kênh điện thoại").

### Lần đo đầu: giới hạn nền theo trung vị lọt lượt giả "ĐÂY"

Bản đầu lấy nền = trung vị. Trên bộ đo dưới đây nó cải thiện mạnh, nhưng có lượt ảo giác trên đoạn
chỉ có nhiễu ở 6/14 điều kiện có nhiễu, mỗi điều kiện 1/12 ("ĐÂY" ×5, "VÂNG" ×1: golden office@8
−15 dB, nói xa office@20 −10 và −20 dB, điện thoại office@20 0 / −15 / −25 dB); tắt tăng âm chỉ có 1
lượt ("Ừ", điện thoại −15 dB). Trace trial
nói xa −10 dB: trung vị nền −61 dBFS cho phép +9 dB, một cụm nhiễu −51 dBFS lên −42 dBFS, Silero gắn
cờ, ASR ra "ĐÂY".

Ngưỡng "Silero không báo nhầm tới −45 dBFS" ở trên đo theo RMS cả đoạn nhiễu, còn trung vị của
nhiễu văn phòng thấp hơn RMS nhiều (404 s nhiễu, cửa sổ 10 s):

| Cửa sổ 10 s, cao hơn trung vị | p10 | p50 | p90 |
|---|---|---|---|
| RMS | 3,1 dB | 9,9 dB | 18,0 dB |
| Phân vị 90 | 4,7 dB | 12,5 dB | 19,4 dB |

Tức giới hạn trung vị −50 dBFS để RMS sau khi tăng lên khoảng −40 dBFS — đúng chỗ Silero bắt đầu báo
nhầm. Mô phỏng chỉ Silero (không ASR) trên cùng trial golden, 24 đoạn chỉ nhiễu mỗi điều kiện; ô =
tỉ lệ frame giọng câu đo được nhận ra · số lần Silero báo nhầm trên đoạn chỉ nhiễu:

| Điều kiện | Tắt | Trung vị | RMS | RMS bỏ 3% frame to nhất | **Phân vị 90** |
|---|---|---|---|---|---|
| sạch −15 dB | 0,738 | 0,778 | 0,787 | 0,796 | **0,796** |
| sạch −25 dB | 0,819 | 0,884 | 0,901 | 0,889 | **0,892** |
| office@20 −15 dB | 0,660 · 0 | 0,754 · 1 | 0,731 · 0 | 0,765 · 1 | **0,754 · 0** |
| office@8 −15 dB | 0,509 · 0 | 0,675 · 2 | 0,561 · 0 | 0,600 · 1 | **0,555 · 0** |
| office@8 −25 dB | 0,301 · 0 | 0,599 · 1 | 0,512 · 0 | 0,551 · 1 | **0,452 · 0** |
| nói xa office@20 −10 dB | 0,640 · 0 | 0,741 · 1 | 0,673 · 0 | 0,706 · 1 | **0,652 · 0** |
| nói xa office@20 −20 dB | 0,222 · 0 | 0,303 · 1 | 0,247 · 1 | 0,272 · 2 | **0,232 · 1** |

Bỏ dù chỉ 3% frame to nhất là báo nhầm quay lại — chính đỉnh cụm nhiễu làm Silero báo nhầm. Phân vị
90 hết báo nhầm như RMS (lần ở nói xa −20 dB có cả khi hệ số chỉ +0,5 dB), giữ trọn lợi ích khi
không có nhiễu, và không bị một tiếng gõ ngắn (< 10% frame) kéo hệ số xuống. Đổi lại, trong nhiễu
từng cụm (văn phòng ồn, nói xa) hệ số nhỏ hơn và lợi ích ít hơn.

**Giá phải trả trên bộ web.** Câu web cắt từ cuộc gọi có khử nhiễu trình duyệt: nền là im lặng số
(trung vị −120 dBFS), nhưng ở −25 dB phần giọng Silero bỏ sót (đầu câu, âm tiết nhỏ) chiếm > 10% số
frame "không có tiếng nói", phân vị 90 rơi vào chính giọng đó (−44…−50 dBFS) và hệ số về gần 0 (mô
phỏng: +4,2 dB, trung vị +14,6 dB). Đã thử và loại hai cách gỡ:
- không tính 450–600 ms trước lúc Silero nhận ra tiếng nói (đầu câu nhận trễ): hệ số web lên +8 dB
  nhưng báo nhầm quay lại ở golden office@20 −15, office@8 −15 dB, nói xa −10 dB — đầu các cụm nhiễu
  (trước lúc Silero gắn cờ cụm đó) cũng bị bỏ;
- nền = min(phân vị 90, trung vị + 15/20 dB): lấy lại trọn lợi ích web nhưng báo nhầm quay lại ở golden
  office@20 −15 dB và web office@20 −25 dB.

### Kênh điện thoại: tiếng lạo xạo G.711

Trên kênh điện thoại mô phỏng (16 kHz → 8 kHz → G.711 μ-law → 16 kHz), bản cuối vẫn thêm lượt ảo giác
ở office@20: 0 dB "ĐÂY" (hệ số chỉ +4,7 dB), −25 dB "VÂNG" (+20 dB); tổng 3/36 đoạn chỉ có nhiễu, tắt
tăng âm 1/36. Nhiễu nhỏ qua μ-law bị lượng tử thô thành tiếng lạo xạo mà Silero gắn cờ, kể cả khi
không tăng âm; tăng âm làm nặng thêm. Silero trên nhiễu văn phòng đã qua G.711, % frame báo nhầm (30
đoạn 10 s):

| RMS nhiễu trước codec | +0 dB | +5 dB | +10 dB | +20 dB |
|---|---|---|---|---|
| −78 dBFS | 14,7% | 20,8% | 25,6% | 46,2% |
| −68 dBFS | 12,6% | 20,9% | 26,7% | 38,1% |
| −58 dBFS | 4,5% | 9,6% | 11,5% | 21,3% |
| −53 dBFS | 0,7% | 5,6% | 8,6% | 13,5% |

(cùng nhiễu, kênh web: 0% tới −45 dBFS). Vì vậy cuộc gọi SIP tắt tăng âm, dù trên đường sạch nó cải
thiện mạnh (bảng dưới). Chưa có dump cuộc gọi SIP thật nào (`temp/audio` chỉ có cuộc gọi web) để biết
nền đường dây thật có rơi vào vùng này không — máy điện thoại thường tự khử nhiễu / chèn comfort noise.

### Cuộc gọi web thật

Chạy bộ tăng âm (cùng Silero) trên 245 dump `temp/audio/livekit_debug_web-*.wav` (236 phút): 32 cuộc
gọi có lúc hệ số > 0, phần lớn do một đoạn Silero gắn cờ ở −40…−60 dBFS trong 0,4–1,8 s đầu — lúc bot
đang chào; câu đầu của người gọi (≈ −20 dBFS) khi đó bị tăng 11–15 dB rồi hệ số tụt sau câu. Dump
không có mốc bot nói nên phép thử này tính cả các đoạn đó; production thì không (`bot_speaking`).
Cuộc gọi duy nhất trong số đó còn log worker (`web-e65cf375`, 07/10) xác nhận: đoạn −56 dBFS lúc 3,3 s
là "Ừ" trong lúc bot chào (`discard candidate on bot_speaking->False`), câu đầu người gọi tới lúc
9,8 s. Thêm `_AFTER_BOT_GUARD_S` (0,5 s sau khi bot dứt lời cũng không tính) cho dư âm / tiếng vọng
phòng kéo dài qua lúc bot dừng.

## Kết quả đo

`eval/noise-bench/level_eval.py` (pipeline LiveKit đầy đủ: Silero, GipFormer, TurnController,
Validator), `--set speaker_gate_mode=off`, tắt → bật tăng âm (bản cuối). Mỗi trial = 2 câu khởi động
+ câu đo (như giữa cuộc gọi); mỗi điều kiện có nhiễu thêm 12 đoạn chỉ có nhiễu 8 s sau 2 câu khởi
động. `whole`: cả cuộc gọi nhỏ đi N dB (mic / đường truyền nhỏ); nói xa: chỉ giọng nhỏ đi, nhiễu
phòng giữ nguyên. Ô = WER lượt so với nhãn (bộ web: so với decode câu sạch) · số câu không thành lượt
nào. Ảo giác = lượt trên đoạn chỉ có nhiễu mà chữ không thuộc câu khởi động (lượt của câu khởi động
chốt muộn không tính).

**Golden, kênh web** (37 câu thật, mức giọng trung vị −33 dBFS — một nửa đã dưới ngưỡng ở "0 dB"):

| Điều kiện | 0 dB | −15 dB | −25 dB |
|---|---|---|---|
| sạch | 0,147 → **0,127** · 0 → 0 | 0,207 → **0,153** · 1 → 1 | 0,340 → **0,213** · 2 → **0** |
| office@20 | 0,153 → 0,153 · 0 → 0 | 0,240 → **0,180** · 2 → **1** | 0,440 → **0,193** · 6 → **1** |
| office@8 | 0,213 → 0,213 · 1 → 1 | 0,453 → **0,427** · 8 → **7** | 0,653 → **0,520** · 16 → **11** |

Ảo giác 0 → 0 ở cả 6 điều kiện có nhiễu (office@20 −25 dB có 1 lượt của câu khởi động chốt muộn).

**Bộ web** (42 câu thật của người thử nghiệm, 16 kHz):

| Điều kiện | 0 dB | −15 dB | −25 dB |
|---|---|---|---|
| sạch | 0,044 → 0,044 · 1 → 1 | 0,055 → 0,051 · 1 → 2 | 0,215 → **0,190** · 8 → 8 |
| office@20 | 0,084 → 0,084 · 1 → 1 | 0,095 → 0,095 · 2 → 2 | 0,153 → 0,150 · 6 → 6 |

Lượt giả trên đoạn chỉ có nhiễu 0 → 0. Sạch −25 dB: 5 câu nhận đúng hơn, 1 câu sai thêm; −15 dB: câu
ngắn "ĐÚNG KHÔNG" mất lượt, một câu khác sửa đúng. Lợi ích nhỏ vì phân vị 90 (mục "Giá phải trả").

**Nói xa mic** (golden, office@20, nhiễu giữ nguyên): −10 dB 0,267 → **0,253** · 2 → **1**; −20 dB
0,780 → 0,773 · 21 → 20; ảo giác 0 → 0. Nhiễu từng cụm giới hạn hệ số nên lợi ích nhỏ (bản trung vị:
0,153, nhưng thêm "ĐÂY").

**Câu đầu cuộc gọi** (không có câu khởi động, golden sạch / office@20 −15 / −25 dB): không đổi ở cả 4
điều kiện — chưa biết mức giọng thì không tăng.

**Kênh điện thoại mô phỏng** (G.711; mặc định TẮT, số đo để quyết định sau):

| Điều kiện | 0 dB | −15 dB | −25 dB |
|---|---|---|---|
| sạch | 0,133 → 0,153 · 0 → 0 | 0,207 → **0,160** · 1 → **0** | 0,507 → **0,233** · 5 → **0** |
| office@20 | 0,300 → 0,293 · 0 → 0 | 0,587 → 0,527 · 1 → 1 | 0,913 → 1,100 · 1 → 1 |

Ảo giác office@20: 0 / 1 / 0 → 1 / 1 / 1 (mục "Kênh điện thoại"). office@20 −25 dB tệ đi vì lượt câu
đo bị nối thêm chữ của câu khởi động: tiếng lạo xạo giữa hai câu sau khi tăng giữ Silero "đang nói".
Sạch 0 dB: 2 câu đổi chữ ("TÔI TÊN NGUYỄN HOÀNG MINH" → "TÔI TÊN NGHĨA HOÀNG", thêm "Ừ" cuối câu).

**Người khác nói gần** (golden, kênh web, giọng nền nhỏ hơn người gọi 6 dB; ô = WER lượt · số đoạn chỉ
có giọng nền thành lượt, trên 12):

| Nền | 0 dB | −15 dB | −25 dB |
|---|---|---|---|
| nhiều người (babble) | 5,56 → 5,56 · 12 → 12 | 5,25 → 5,42 · 11 → 11 | 4,62 → 4,88 · 12 → 12 |
| một người khác (voice2) | 3,54 → 3,54 · 12 → 12 | 3,00 → 3,23 · 8 → 8 | 2,83 → 2,89 · 9 → 10 |

Bản gốc đã chép lời người kia ở mọi mức (WER > 2,8). Giọng nền bị Silero gắn cờ như giọng người gọi
nên được tăng cùng, kết quả tiến về mức 0 dB: tệ thêm một chút, voice2 −25 dB thêm 1 lượt.

## Kiểm chứng

| Lệnh / test | Kết quả |
|---|---|
| `tests/speech/audio/test_quiet_gain.py` (mới, 16 ca) | Pass. Ca nhiễu từng cụm thất bại khi nền = trung vị, ca tiếng gõ đơn lẻ thất bại khi nền = RMS, ca dư âm sau lúc bot dừng thất bại khi bỏ `_AFTER_BOT_GUARD_S` |
| `ruff check` / `ruff format --check` (src, tests, eval/noise-bench) | Pass |
| `STT_EVAL_ENABLED=false PYTHONPATH=src python -m pytest -q` (config mới: web bật, SIP tắt) | 5204 passed, 9 skipped |

## Còn mở

- **Cuộc gọi SIP tắt tăng âm** vì tiếng lạo xạo G.711 trên kênh mô phỏng, dù đường sạch cải thiện mạnh
  (giọng nhỏ 25 dB: mất lượt 5 → 0). Cần vài cuộc gọi SIP thật có dump (`LIVEKIT_DEBUG_DUMP_AUDIO`) để
  đo nền đường dây rồi mới bật (hoặc thêm giới hạn nền riêng cho điện thoại).
- **Câu đầu cuộc gọi** của người nói nhỏ chưa được tăng (chưa biết mức giọng).
- **Giọng web rất nhỏ** (−25 dB): phần giọng Silero bỏ sót bị tính vào nền, hệ số nhỏ (mục "Giá phải
  trả").
- **Người khác / TV nói gần** (babble, voice2 nhỏ hơn người gọi 6 dB): bản gốc đã chép lời người kia
  (WER lượt 2,8–5,6, 8–12/12 lượt giả); tăng âm kéo về gần mức 0 dB nên tệ thêm một chút (bảng trên).
  Cần cổng giọng người gọi, không phải mức âm.
- **Người gọi tự đổi mức** (lúc to lúc nhỏ): bộ tăng âm không tự gây "trí nhớ mức âm" của Silero
  nhưng cũng không chữa được khi chính người gọi đổi mức.
- Chưa thử trên cuộc gọi thật: theo dõi log `quiet_gain: gain=… speech=… floor=…` (ghi khi hệ số đổi
  ≥ 3 dB).
