# Evidence: Kênh điện thoại, tiếng bot vọng lại, pre-roll điện thoại, cổng giọng người gọi — 07/10/2026

## Mục tiêu

Mục tiêu cuối là dịch vụ điện thoại (SIP → LiveKit → cùng pipeline với web). Đo các hướng của
kế hoạch xử lý nhiễu/nhiều người nói trong điều kiện điện thoại, chỉ giữ thứ số đo ủng hộ. Thứ bị
từ chối thì gỡ code, chỉ để lại số đo và script đo.

| # | Việc | Kết quả |
|---|---|---|
| 1 | Kênh điện thoại + giọng người thứ hai + bot nói có echo trong `eval/noise-bench` | **Giữ** — công cụ đo; kênh web cho kết quả trùng từng byte với mốc cũ |
| 2 | Tiếng bot vọng lại thành lượt của người gọi | **Sửa** — lượt giả 11–12/12 → 0/12; lượt người gọi chen vào hết lẫn câu bot |
| 3 | Pre-roll 1000 ms cho cuộc gọi SIP (`phone_overrides`) | **Giữ** — WER golden sạch 0,147 → 0,087; web giữ 300 ms |
| 4 | Cổng giọng người gọi (speaker embedding) | **Thêm, THỬ NGHIỆM, mặc định tắt** (`speaker_gate_mode`) — giọng mẫu cùng cuộc gọi, chỉ xét lượt ≥ 2 s; giọng mẫu khác cuộc gọi thì không đạt |
| 5 | Xác nhận ngắt lời bằng phần còn lại sau khi bỏ echo | **Từ chối, đã gỡ** — không tăng số lần xác nhận, có biến thể làm bot tự ngắt lời |
| 6 | Tạm dừng bot ngay khi có ứng viên ngắt lời (LiveKit) | **Từ chối, không viết code** — echo tạo ứng viên ở 12/12 câu bot |
| 7 | Câu chỉ có từ đệm ("ừ/à/ờ/dạ") gửi engine (`turn_drop_filler_words: false`) | **Bật theo yêu cầu owner để thử trực tiếp — chưa có số đo hợp lệ**; từ đệm lúc bot nói vẫn bỏ |
| 8 | Chặn "Ừ" giả: ngưỡng SNR riêng, speaker embedding, chờ thêm, xác suất Silero, audio tagging | **Chưa kết luận, đã gỡ** — cùng lý do |
| 9 | Nhận echo bằng giọng bot (speaker embedding) | **Chưa tích hợp** — tách được trên mô phỏng, biên hẹp với giọng mẫu TTS sạch |

Các script đo speaker embedding, câu 1 âm tiết và audio tagging chạy tạm trong `temp/`, không
commit; số đo giữ ở dưới.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| Bench mô phỏng đường SIP | `eval/noise-bench/bench.py` `--channel phone`: `phone_channel` (16 kHz → 8 kHz → G.711 μ-law → 16 kHz). Bộ mã hoá μ-law lượng tử theo đúng bảng giải mã của `speech.audio.g711` (mã hoá–giải mã khớp bảng, SQNR 37,5 dB ≈ chuẩn G.711) |
| Giọng người thứ hai | `build_voice2`: một người nói có ngắt nghỉ 0,3–1,5 s; mức trộn tính trên đoạn có giọng. Giọng lấy từ bộ khác người (golden ↔ web) |
| Bot nói + echo | `BotTurn` + `run_pipeline(..., bot=)`: báo bot nói/dừng như `CallBridge._speak`, InterruptionController thật, echo dừng khi ngắt lời được xác nhận. `eval/noise-bench/barge_in_eval.py` |
| Echo không thành lượt người gọi | `STTPipeline` (`_unconfirmed_barge_in_audio`) → `TurnController.expect_echo` → `strip_echo_prefix` lúc chốt. Test: `test_bot_stopping_with_unconfirmed_candidate_keeps_only_caller_words` (2 ca), `test_confirmed_barge_in_turn_drops_echoed_bot_words`, `test_strip_echo_prefix` (5 ca), `test_bot_sentence_echoed_with_misheard_words_does_not_confirm_barge_in` |
| Pre-roll riêng cho điện thoại | `pre_speech_ms` theo từng stream (ZipFormer, Gemini Live; ElevenLabs nhận và bỏ qua) như `min_decode_ms`; `SpeechSettings.asr_pre_speech_ms`, `phone_overrides`, `for_phone()`; worker `speech_settings_for(participant.kind, ...)`. Test: `test_stream_pre_speech_override_replaces_config_for_this_stream`, `tests/transports/livekit/test_worker_speech_settings.py` |
| Câu chỉ có từ đệm tới engine; tiếng đệm lúc bot nói vẫn bỏ | `TurnController(drop_filler_words=...)` (`keep_filler` tắt khi `candidate.echo_text`), `SpeechSettings.turn_drop_filler_words`. Test: `test_single_syllable_reply_is_a_turn_when_filler_words_are_kept` (4 ca), `test_punctuation_only_is_dropped_even_when_filler_words_are_kept`, `test_filler_heard_while_bot_was_speaking_is_still_dropped` |
| Cổng giọng người gọi (thử nghiệm) | `speech/audio/speaker_gate.py`, `STTPipeline(speaker_gate=...)` giữ audio từng lượt và hỏi cổng trước khi trả lượt; `speaker_gate_*` trong `config/speech.yaml`. Test: `tests/speech/test_speaker_gate.py`, `test_turn_rejected_by_speaker_gate_is_not_yielded` |
| Bench dựng TurnController đúng như worker | `speech.bundle.turn_controller_options` dùng chung cho bundle và bench (trước đây bench chép lại từng tham số) |

## Lỗi tiếng bot vọng lại (echo)

**Hiện tượng (barge_in_eval, mốc trước khi sửa):** khi bot nói, tiếng bot vọng lại (AEC của máy/nhà
mạng không khử hết) làm VAD báo có giọng → InterruptionController thành ứng viên → pipeline gửi
audio vào ASR để xác nhận. Gate echo chặn đúng (không ngắt lời giả), nhưng khi bot dứt lời
TurnController bỏ lượt dở còn ASR vẫn giữ đoạn đó: final tới sau thành **lượt người gọi chép lại
câu bot** ("DẠ VINMEX XIN NGHE EM LÀ TRỢ LÝ ẢO AI…"). Người gọi chen vào thì lượt bị ghép câu bot
ở đầu: "ANH CHỊ CHẮC CHẮN MUỐN HỦY TÔI LÀ NGUYỄN VĂN A" — engine có thể đọc ra ý "hủy" từ chính
câu bot.

**Sửa:** giữ đoạn ASR (có thể có lời người gọi), bỏ phần đầu trùng câu bot khi chốt lượt —
`strip_echo_prefix` so khớp theo TỪ (difflib). So mờ ký tự (rapidfuzz) trên cả phần đầu đã thử
và loại: ăn luôn lời người gọi ("TÔI TÊN LÀ NGUYỄN VĂN A" → "VĂN A").

Kết quả (`barge_in_eval.py`, 12 câu bot × trial chỉ echo, 39 lần người gọi chen vào — 19 câu
ngắn, phần lớn "Ừ" vốn bị lọc — và 20 lần người khác chen vào; echo nhỏ hơn giọng người gọi
30/20/10 dB):

| Kênh / echo | Echo thành lượt (mốc → sau) | Lượt người gọi lẫn câu bot | Bot tự ngắt lời | Ngắt lời thật được xác nhận | Lượt có lời người gọi |
|---|---|---|---|---|---|
| phone −30 dB | 12/12 → **0/12** | 19 → **0** | 0 → 0 | 18 → 18 | giữ đủ |
| phone −20 dB | 12/12 → **0/12** | 37 → **0** | 0 → 0 | 12 → 12 | giữ đủ |
| phone −10 dB | 11/12 → **0/12** | 38 → **0** | 0 → 0 | 11 → 11 | giữ đủ |
| web −30 dB | 11/12 → **0/12** | 29 → **0** | 0 → 0 | 15 → 15 | giữ đủ |
| web −20 dB | 11/12 → **0/12** | 36 → **1** | 0 → 0 | 13 → 13 | giữ đủ |
| web −10 dB | 11/12 → **0/12** | 37 → **0** | 0 → 0 | 7 → 7 | giữ đủ |

"Giữ đủ": mọi trial mà ở mốc lượt có lời người gọi thì sau khi sửa vẫn có lượt đó (đã sạch câu
bot); các trial "mất lượt" so với mốc là trial mà lượt ở mốc chỉ toàn câu bot.

**Các biến thể đã thử và loại:**

| Biến thể | Kết quả | Quyết định |
|---|---|---|
| Bỏ hẳn đoạn ASR khi bot dứt lời | Hết echo thành lượt, nhưng người gọi chen vào mà chưa được xác nhận mất luôn câu; lượt được xác nhận vẫn lẫn câu bot (11) | Loại |
| Gate ngắt lời xét phần còn lại sau echo | Xác nhận 12 → 27/39 nhưng **bot tự ngắt lời 2–3/12** (đuôi câu bot chép sai: "…HỦY LỊCH HẢ", "NÓI LÀ") | Loại |
| + đòi phần còn lại ổn định qua 2 partial | Hết tự ngắt lời nhưng xác nhận về lại như cũ, ở echo −10 dB còn giảm 11 → 7 | Loại, gate giữ nguyên như trước |

**Chưa giải quyết:** ngắt lời thật chỉ được xác nhận 7–18/39 lần (trễ trung vị 1,1–1,4 s) khi có
echo — partial gồm cả câu bot nên gate echo coi là echo. Câu của người gọi không mất (thành lượt
sau khi bot dứt lời), nhưng bot nói hết câu mới nghe.

**Tạm dừng → phát tiếp (LiveKit `resume_false_interruption`):** echo tạo ứng viên ngắt lời ở
**12/12** câu bot ở mọi mức (kể cả −30 dB, Silero không có ngưỡng độ to) — tạm dừng khi có ứng viên
thì bot dừng ở mọi câu. Không làm.

## Pre-roll cho cuộc gọi điện thoại

`noise-bench --channel phone`, `ZIPFORMER_PRE_SPEECH_MS` 300 (mốc) / 600 / 1000.

| WER lượt so với nhãn — golden (ghi điện thoại thật) | 300 | 600 | 1000 |
|---|---|---|---|
| clean | 0,147 | 0,100 | **0,087** |
| office@15 | 0,263 | 0,173 | **0,113** |
| office@8 | 0,413 | 0,347 | **0,263** |
| office@3 | 0,660 | 0,597 | **0,560** |
| babble@12 / voice2@6 | 1,550 / 1,237 | 1,637 / 1,310 | 1,677 / 1,393 |

- `no_turn`, `false_turns` của golden không đổi đáng kể ở mọi điều kiện.
- Bộ web qua kênh điện thoại: WER lệch so với decode sạch, điều kiện clean 0,063 → 0,022 (600) / 0,037 (1000), office ngang hoặc tốt hơn; babble@6 thêm 1 lượt giả (11 → 12/12).
- Bộ câu ngắn (nhãn chưa kiểm, xem mục "Câu 1 âm tiết"): 1000 ms đổi "CŨNG ĐƯỢC" → "KHÔNG ĐƯỢC", "Ừ" → "THÔI", "TIẾP THEO" → "OK", "Ừ" → "VÂNG" (chữ GipFormer đoán trên đoạn sạch ở vế sau), thêm lượt "ĐÂY" (2 khi sạch, 1 ở office@3). Chỉ là ví dụ; quyết định dựa trên bộ golden.
- Babble/voice2: WER tăng nhẹ do pre-roll dài kéo thêm giọng người khác. Vốn đã > 1 nên không đổi quyết định.

Quyết định: `phone_overrides.asr_pre_speech_ms: 1000` cho participant SIP. Web giữ 300 ms
(đo 06/10 trên web: trái chiều).

## Cổng giọng người gọi (speaker embedding)

**Khả thi** (64 người VIVOS test + người thử nghiệm + người đọc bộ PM; giọng
mẫu = 2 câu; EER, kênh điện thoại):

| Model (sherpa-onnx) | sạch 1 s | sạch 2 s | office@8 1 s | giọng khác chồng 6 dB, 1 s | ms/đoạn* |
|---|---|---|---|---|---|
| NeMo TitaNet-small | 7,3% | 3,7% | 11,0% | 3,3% | 97 |
| 3D-Speaker CAM++ (zh_en) | 9,3% | 4,5% | 11,0% | 4,0% | 127 |
| 3D-Speaker ERes2NetV2 | 5,3% | 2,9% | 8,0% | 2,3% | 472 |
| WeSpeaker ResNet34 | 24,3% | 18,3% | — | — | — (dừng sớm) |

\* Đo khi CPU đang chạy song song nhiều phép đo khác, chỉ để so tương đối.

- Đoạn 0,5 s: EER 13–19%.
- Kênh web và kênh điện thoại chênh nhau không đáng kể.
- Ngưỡng tối ưu đổi theo độ dài đoạn: 0,37 ở 0,5 s, 0,71 ở 3 s (TitaNet).

**Đo bóng trên pipeline** (bộ web — giọng thật của người thử nghiệm qua nhiều cuộc gọi; giọng mẫu
2 câu web sạch; người khác từ VIVOS; kênh điện thoại; TitaNet; miễn chặn lượt < 1 s):

| Điều kiện | Cả lượt, ngưỡng 0,3: câu thật bị chặn / lượt giả bị chặn | Cửa sổ con 1 s, ngưỡng 0,2 | Cửa sổ con, ngưỡng 0,3 |
|---|---|---|---|
| clean | 3/39 / — | 1/39 / — | 4/39 / — |
| office@8 | 1/23 / 1/1 | 0/23 / 0/1 | 1/23 / 1/1 |
| voice2@6 | **35/40** / 12/12 | 4/40 / 9/12 | 8/40 / 12/12 |
| voice2@0 | **36/40** / 12/12 | 3/40 / 9/12 | 10/40 / 12/12 |
| babble@6 | 11/12 / 5/5 | 0/12 / 5/5 | 6/12 / 5/5 |

- Lượt giả do người khác nói một mình có similarity 0,0–0,3, tách khá rõ.
- Chặn theo cả lượt thì hỏng: VAD gộp lời người gọi với lời người bên cạnh thành một lượt, embedding của lượt nghiêng về người kia.
- Chặn theo cửa sổ con tốt hơn nhiều nhưng vẫn chặn nhầm 7,5–10% câu thật khi có người bên cạnh nói, chưa đạt tiêu chí đặt trước (≤ 2%). Nguyên nhân chính: cùng một người qua các cuộc gọi khác ngày, khác mic cho similarity thấp (p10 = 0,37 khi sạch).

Đo lại với giọng mẫu lấy **trong cùng cuộc gọi** (16 cuộc gọi của bộ web có ≥ 2 câu: giọng mẫu =
câu đầu, thử = các câu sau; người khác = 200 câu VIVOS; không phải người = nhiễu văn phòng;
TitaNet-small):

| Đoạn thử | Kênh | EER với người khác | Ngưỡng giữ 98% câu thật | Người khác bị chặn | Nhiễu bị chặn |
|---|---|---|---|---|---|
| 0,5 s | điện thoại / web | 25% / 25% | — | — | — |
| 1 s | điện thoại / web | 16% / 16% | — | — | — |
| 2 s | điện thoại | 7% | 0,24 | 97% | 65% |
| 2 s | web | 0,9% | 0,23 | 98% | 96% |

Câu thật ít (14–24); bộ web do máy cắt theo chữ kịch bản, chưa nghe lại.

Quyết định: thêm `speech/audio/speaker_gate.py` dạng **THỬ NGHIỆM, mặc định tắt**
(`speaker_gate_mode: off | log | enforce`). Giọng mẫu = lượt đầu có ≥ 2 s tiếng nói; chỉ xét lượt
≥ 2 s, ngưỡng 0,2; lượt ngắn không bao giờ bị chặn. Cần thử trực tiếp (cùng mic, người thật bên
cạnh) trước khi bật mặc định. Chưa xử lý: lượt dài đầu tiên lại là người khác.

## Câu 1 âm tiết ("ừ/à/ờ/dạ") — số đo không hợp lệ

Owner muốn bot nghe được câu 1 âm tiết; engine đã hiểu chúng (`agreement.py`: "ừ/ờ/vâng" đồng ý,
"dạ" hỏi lại). Các phép đo ngày 07/10 (cho từ đệm qua; ngưỡng SNR riêng; chờ thêm sau câu 1 âm
tiết; speaker embedding; xác suất Silero; audio tagging CED-mini) đều lấy "câu 1 âm tiết THẬT" từ
bộ `short` của noise-bench (`temp/noise-bench/short_set.json`, tạo 28/09).

**Owner nghe lại 07/10: phần lớn đoạn "Ừ" trong bộ đó không phải người nói "ừ".** Bộ được chọn tự
động theo chữ GipFormer đoán trên đoạn sạch, không có nhãn tay; 5/10 đoạn "Ừ" nằm ở giây đầu bản
ghi, 2 đoạn chồng lên nhau. Vì vậy "nghe thêm được 6 → 14/19 câu 1 âm tiết" thực chất là gửi thêm
cho engine những âm không phải "ừ" — tức đồng ý giả. Mọi kết luận về câu 1 âm tiết của ngày này
bị huỷ. `turn_drop_filler_words: false` vẫn được bật theo yêu cầu owner để thử trực tiếp (từ đệm
nói lúc bot đang nói vẫn bỏ); tắt nhanh: `TURN_DROP_FILLER_WORDS=true`.

Còn đúng: "Ừ/À/ĐÂY" giả trong trial chỉ có nhiễu văn phòng (7 lượt trên 240 trial ~3 s, kênh
điện thoại) — nhãn giả là chắc chắn vì không có giọng người.

Cũng sai cùng lý do: con số "Ừ thật, confidence trung vị 0,746" trong
`stt-turn-segments-backchannel-fallback-2026-10-06.md`. Quyết định khi đó (không cho từ đệm qua)
không đổi.

Cần trước khi đo lại: tập "ừ/à/ờ/dạ/vâng/có/không" ghi thật, có nhãn người nghe, nhiều người gọi,
qua điện thoại. Tập nghe kiểm tra bộ cũ: `temp/noise-bench/listen_check/` (`nhan.csv`).

## Không đo được / chưa làm

- **Thời gian chờ hết lượt tự học (LiveKit DynamicEndpointing):** câu bị tách trong bench chỉ xuất hiện khi có giọng người khác (`split_turns` clean = 0). Bench không đo được lợi ích, chỉ đo được rủi ro (giữ lượt 300 ms ngày 06/10 hỏng với babble). Hoãn tới khi có ghi âm thật người gọi ngập ngừng.
- **Cổng độ to cho VAD:** lượt giả do nhiễu văn phòng trên kênh điện thoại chỉ 0–1/12; echo thì vượt nhiễu nền rất xa. Không có gì để cải thiện bằng cổng này.
- **A/B xử lý âm thanh trình duyệt:** chỉ áp cho web, ưu tiên thấp vì mục tiêu là điện thoại.

## Quy trình xác minh

```bash
python -m ruff check src tests eval/noise-bench
python -m ruff format --check src tests eval/noise-bench
STT_EVAL_ENABLED=false python -m pytest -q
python scripts/export_openapi.py --check
PYTHONPATH=src python eval/noise-bench/bench.py --label x --dataset golden --channel phone \
  --conditions clean,office@15,office@8,office@3,babble@12,babble@6,voice2@6,voice2@3,voice2@0
PYTHONPATH=src python eval/noise-bench/barge_in_eval.py --label x
```

Dữ liệu/model không commit: `temp/datasets/vivos/test.parquet` (VIVOS, CC BY-NC-SA — chỉ đo nội
bộ), `temp/models/speaker/*.onnx` (sherpa-onnx speaker-recongition-models), kết quả
`temp/noise-bench/results/{ph_*,w_*,barge_*,speaker_*}.json`.

## Kết quả xác minh cục bộ (2026-10-07)

| Command | Kết quả |
| --- | --- |
| `ruff check` / `ruff format --check` (src, tests, eval/noise-bench) | Pass |
| `STT_EVAL_ENABLED=false python -m pytest -q` | Pass (4222 passed, 9 skipped) |
| `scripts/export_openapi.py --check` | Pass |
| `noise-bench` kênh web, `turn_drop_filler_words=true`, `speaker_gate_mode=off`, code cuối vs mốc 06/10 | Giống hệt mọi chỉ số và mọi câu (bộ short) |
| `barge_in_eval` code cuối vs biến thể echo đã chọn | Giống hệt (echo thành lượt 0/12, bot tự ngắt lời 0/12 ở mọi mức) |
