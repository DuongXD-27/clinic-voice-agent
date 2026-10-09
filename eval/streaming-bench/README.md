# Eval Gemini Live và GipFormer trên audio streaming

Chạy từ thư mục gốc repo. Runner phát PCM từng frame 30 ms ở tốc độ **1x**, producer
độc lập với decode. Không dùng đồng hồ ảo, không gọi ASR batch của Gemini. Pipeline dùng
`build_streaming_bundle` và TurnController của worker; tap lưu ASR event trước controller
và turn sau controller. Runner thay TTS factory bằng gateway giả trong phạm vi eval,
không cần key TTS, không gọi phòng khám và không thêm hook vào `src`.

Plan và kết quả thử local: `temp/stt-review-2026-10-05/`; các run gốc ở
`temp/streaming-eval/`. Refactor main ngày 05/10 thay đổi pipeline/config: cần run mới
để đo phiên bản hiện tại, không ghép với baseline đã đo trước refactor.

## Chạy so sánh

```bash
# Chỉ kiểm tra nhãn/file; không gọi model.
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset pm --pm-clean --validate-only

# PM gốc 16 kHz: 30 ca, cùng endpoint/gates, hai provider xen kẽ theo ca.
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset pm --pm-clean \
  --out temp/streaming-eval/pm-clean-paired

# Giữ cả biến thể noise/xa/chồng tiếng để kiểm tra độ bền.
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset pm --out temp/streaming-eval/pm-all-paired

# Đường điện thoại: đọc bản 8k của cùng corpus, nâng về pipeline 16k.
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset pm --pm-rate 8000 \
  --out temp/streaming-eval/pm-8k-paired

# Bộ 40 golden có entity labels đã có của dự án.
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset golden --out temp/streaming-eval/golden-paired
```

`zipformer` là tên provider trong repo; metadata ghi model thực tế từ config, mặc định
`g-group-ai-lab/gipformer1.5-68M-rnnt`. Runner chọn provider tường minh, không phụ thuộc
`LIVEKIT_ASR_PROVIDER` đang bật. Không đổi `.env` hoặc restart worker đang phục vụ mic.
Mỗi thư mục output phải mới/rỗng để không trộn các lần chạy.

Đường Gemini sẽ gửi audio của corpus tới Google để phiên âm. Key lấy từ `.env`.
Khi chạy trong Codex, nếu công cụ yêu cầu xác nhận việc gửi corpus, cần người dùng xác
nhận corpus đó trước phần Gemini. Có thể hoàn thành baseline local trước:

```bash
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset pm --pm-clean --providers zipformer \
  --out temp/streaming-eval/pm-gipformer

PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset pm --pm-clean --providers gemini_live \
  --out temp/streaming-eval/pm-gemini

PYTHONPATH=src python eval/streaming-bench/compare.py \
  temp/streaming-eval/pm-gipformer temp/streaming-eval/pm-gemini \
  --out temp/streaming-eval/pm-comparison
```

So các lần riêng chỉ được khi case IDs, SHA256 audio, reference, rate, ranh giới và snapshot
code/cấu hình giống nhau. Không tái dùng baseline sau khi sửa pipeline hoặc runner.
Với manifest có speech offsets, chạy hai provider trong cùng một lệnh paired; các artifact
v1 hiện chưa lưu offset thành cột CSV riêng nên comparator từ chối ghép hai run kiểu đó.

## Hai chế độ để tìm nguyên nhân

| Chế độ | Cách chạy | Trả lời |
|---|---|---|
| `pipeline` (mặc định) | Local VAD + provider endpoint + controller/validator như cấu hình hiện tại | ASR nghe gì, bao nhiêu lời được giữ thành turn |
| `asr` | Toàn bộ clip đi vào provider, bỏ speech admission, đóng input tại cuối WAV | Khi nhận đủ audio với ranh giới đã cho, model có nhận đúng không |

Dùng `--modes asr pipeline` để chạy cả hai. `asr` là cấu hình kiểm soát riêng, không dùng
để báo latency production hoặc đánh giá false-turn của VAD. Ngưỡng min decode/max speech
của adapter vẫn giữ theo config; không ép GipFormer nhận câu ngắn theo cách riêng.
`pipeline` chèn 300 ms silence trước và 2000 ms sau clip, không thêm DSP. API Gemini
dùng endpoint local và manual activity theo adapter đã tích hợp.

`--case ID` có thể lặp; `--limit N` chỉ là subset đầu của dataset, không phải tập đại diện.
Muốn thử câu phủ định trước:

```bash
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --dataset pm --pm-clean --modes asr pipeline \
  --case B-YN-03_S01 --case B-YN-04_S01 \
  --out temp/streaming-eval/negation-smoke
```

## Output và cách đọc

- `events.jsonl`: audio time và wall time, bytes từng frame, partial/final, generation/segment,
  turn và các lần controller emit/reset quan sát trong eval. Text nằm ở artifact local này,
  không in transcript trong progress.
  `audio_fed_ms` là audio đã đưa vào queue nguồn, không phải ACK hay số mẫu Google đã nhận.
- `cases.csv`: reference, ASR final, turn text, WER/CER, phủ định, critical check, mất final,
  mất turn, split/extra turn, lỗi, pacing lag/backlog và drop reasons cho từng ca.
- `summary.json`: snapshot cấu hình/model/code, micro WER/CER, exact-match, content-pass,
  lỗi và latency; breakdown theo category/condition/source rate.
- `comparison.md`: bảng paired và IDs các ca cải thiện/thụt lùi.

**Ưu tiên chất lượng trước latency:**

1. So micro WER/CER và exact-match ở ASR final. Missing final/error vẫn tính là ca thất bại;
   không loại chúng khỏi mẫu số WER/content-pass.
2. Kiểm tra `negation_failures`, entity errors của golden và những ca tên/ngày sinh/hủy.
   Negation check so chuỗi từ `không/chưa/chẳng/đừng`, gồm cả việc model thêm phủ định.
   Đây là heuristic về nội dung từ, không phải chấm ý định bằng LLM.
3. So cùng metric ở turn text; `dropped_after_asr` nghĩa adapter có final nhưng controller
   không phát turn. `drop_reasons=controller_reset` chỉ cho biết candidate có text bị reset;
   chưa xác định gate cụ thể trong phiên bản main mới. Một clip một lượt: nhiều turn là
   `extra_turns`; đọc timeline để phân biệt split/duplicate. Chưa thử merge nhiều clip.
4. Kiểm tra false-turn/hallucination trên nền và silence. PM sạch chỉ có 1 ca silence,
   chưa đủ kết luận về tiếng nền hoặc echo. Dùng golden/nhiễu và bot-only fixtures bổ sung.
5. So first partial, final và turn latency p50/p95. `first_partial_ms` là partial có chữ
   đầu tiên, chưa bảo đảm từ đó đúng/hữu ích. `partial_revision_edits` là tổng edit giữa
   các partial liên tiếp. Latency chỉ có trên event nhận được; luôn đọc tỷ lệ lỗi/mất lượt
   cạnh latency. P95 cần ít nhất 20 event; cold load GipFormer được warm-up và ghi riêng.

WER tách theo khoảng trắng nên tiếng Việt phần lớn đo lỗi âm tiết; CER bỏ khoảng trắng.
Chuẩn hóa NFC, case và punctuation, giữ dấu, số và phủ định. Không đổi số “14” thành
“mười bốn” để làm đẹp score. Entity matcher dùng đúng evaluator golden hiện có.

## Nhãn và mốc latency

PM loại `B-HOLD-01`, `B-AUD-RATE` chưa được nghe lại/chốt, helper `B-OVER-01-CHEN`,
và biến thể `matdau/chong` cần nhãn/cách chọn người nói riêng. Áp lời thật đã chốt của
`B-VM-01` cho cả bản gốc và biến thể. Silence reference rỗng. Các lời còn lại là kịch bản
thu của PM (`PM_script_reference`), chưa được runner biến thành nhãn xác nhận bởi model.
Vì PM chưa có entity labels riêng, `critical_pass` dùng khớp toàn câu nghiêm ngặt; đọc
đây là proxy, không phải tỷ lệ lỗi nghiệp vụ đã gắn nhãn tay. Golden dùng entity labels
của bộ cũ; các bất đồng reference/audio cần nghe lại trước quyết định thay model.

Mặc định latency tính từ **cuối WAV**, không phải offset giọng đã gắn nhãn. File có silence
ở đuôi có thể cho latency âm; runner giữ số âm và đếm chúng, không clamp che vấn đề.
Để có kết luận latency đáng tin, cung cấp `speech_start_ms`/`speech_end_ms` đã nghe/gắn nhãn:

```json
{"id":"negation_01","audio":"audio/negation_01.wav","reference":"Không, tôi chưa đồng ý.","category":"negation","condition":"clean","critical":true,"critical_entities":[{"type":"negation","value":"chưa đồng ý"}],"speech_start_ms":210,"speech_end_ms":1840,"label_source":"human_reviewed"}
```

Lưu nhiều dòng vào manifest JSONL, đường dẫn audio tính từ manifest, rồi chạy:

```bash
PYTHONPATH=src python eval/streaming-bench/bench.py \
  --manifest temp/my-streaming-set/manifest.jsonl \
  --out temp/streaming-eval/my-set-paired
```

## Phạm vi kết luận

Đây là replay cùng pipeline trước transport: **chưa đo mạng LiveKit, browser AEC/AGC,
Krisp ingress, TTS, barge-in thật, CPU/RAM dưới tải hoặc writes/outcome nghiệp vụ**.
`turn_latency_ms` là thời gian tới `UserTurnCompleted`, sẵn sàng làm input engine; không
gọi orchestrator. Dùng `scripts/bench/livekit_call.py --wav ...` để kiểm tra E2E sau khi
chọn ứng viên, với cùng audio và mock scenario; các phép đo đó bổ sung cho bộ eval này.
Chưa thể thay baseline chỉ dựa vào một lượt smoke hoặc WER thấp hơn nhưng rơi phủ định.
