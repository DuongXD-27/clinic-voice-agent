# API thử chất lượng STT — `/v1/stt/*`

Dành cho PM và QA: gửi một file WAV, nhận lại transcript, độ tin cậy (`confidence`) và thời gian xử lý của từng bước. API không mở cuộc gọi và không ghi trace, nên không làm lệch số liệu STT của cuộc gọi thật.

Có hai chế độ:

| Chế độ | Route | Dùng khi | Cách xử lý |
|---|---|---|---|
| **Một lượt nói** | `/v1/stt/turn`, `/v1/stt/turn/upload` | File là **một câu trả lời** của người gọi, giống mỗi `audio_url` mà harness gửi cho `/v1/calls/{call_id}/turn`. Tối đa 30 s | Tiền xử lý nhẹ, rồi model nhận dạng **nguyên clip một lần** |
| **File dài nhiều câu** | `/v1/stt/transcribe`, `/v1/stt/transcribe/upload` | Bản ghi cả cuộc gọi, hoặc nhiều câu liền nhau. Tối đa 5 phút | Tiền xử lý, VAD cắt thành từng câu, nhận dạng từng câu rồi ghép lại |

Code: [stt_eval.py](../../src/callbot/transports/http/stt_eval.py) (HTTP), [offline.py](../../src/speech/asr/offline.py) (pipeline), [preprocess.py](../../src/speech/audio/preprocess.py) (xử lý audio). Evidence và số đo: [stt-eval-api-2026-09-29.md](../evidence/stt-eval-api-2026-09-29.md).

## Bật API

Mặc định tắt. Đặt trong `.env` rồi khởi động lại server:

```env
STT_EVAL_ENABLED=true
BOT_API_KEYS=sk_...   # bắt buộc khi bật: server không khởi động nếu thiếu
```

Mọi request cần header `Authorization: Bearer <key>`. Cách dễ nhất để thử: mở `http://<server>:8000/docs`, bấm **Authorize**, điền key, rồi dùng mục **stt-eval**.

Giới hạn chung:
- File tối đa 25 MiB.
- `audio_url` phải là http(s) tới địa chỉ public. Localhost, IP nội bộ và link redirect về nội bộ đều bị từ chối; file trên máy thì dùng route `/upload`.
- Nhận WAV PCM 8/16/24/32-bit, float 32/64-bit, A-law, μ-law, WAVE_FORMAT_EXTENSIBLE; mono hoặc stereo; tần số bất kỳ.

## 1. Một lượt nói — `/v1/stt/turn`

```bash
# File trên máy
curl -X POST http://localhost:8000/v1/stt/turn/upload \
  -H "Authorization: Bearer $KEY" \
  -F "file=@huy-lich.wav" -F "compare=true"

# File có link public
curl -X POST http://localhost:8000/v1/stt/turn \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"audio_url": "https://.../huy-lich.wav", "compare": true}'
```

Hai tuỳ chọn:
- **`compare`**: chạy thêm bản `production`, xử lý **y hệt `POST /v1/calls/{call_id}/turn`**: giữ tần số gốc của file, không tiền xử lý. Nhờ đó PM thấy bot hiện tại nghe ra gì với clip này, và tiền xử lý có giúp gì không.
- **`telephone_band`**: hạ file về 8 kHz trước, giống đường điện thoại. File thu bằng máy tính hay điện thoại thường là 16–48 kHz, nên cho kết quả **tốt hơn** lúc gọi thật.

### Xử lý

1. Đọc WAV, trộn về mono.
2. Bỏ DC offset.
3. Resample **một lần, thẳng về 16 kHz**.
4. **Cổng im lặng:** Silero không thấy giọng **và** cả clip nhỏ hơn −55 dBFS thì trả `text` rỗng, không gọi model (bước `VAD_NO_SPEECH`). Tắt bằng `STT_EVAL_SILENCE_GATE=false`.
5. Khuếch đại nếu clip quá nhỏ (giọng dưới −35 dBFS).
6. Model nhận dạng **nguyên clip một lần**, không cắt đoạn.

Lý do từng bước xem [phần Tiền xử lý](#tiền-xử-lý-làm-gì-và-vì-sao).

### Kết quả

Ví dụ thật, câu golden `STT_CF_01` ("Có, tôi đến được."), gọi với `compare=true`:

```jsonc
{
  "text": "CÓ TÔI ĐẾN ĐƯỢC",
  "confidence": 0.995,
  "is_silence": false,
  "production": {"text": "CÓ TÔI ĐẾN ĐƯỢC", "confidence": 0.995, "asr_ms": 55.0},  // chỉ khi compare=true
  "model": {"provider": "zipformer", "model": "g-group-ai-lab/gipformer1.5-68M-rnnt", "input_sample_rate": 16000},
  "audio": {"source": "upload", "size_bytes": 65614, "format": "PCM_16", "sample_rate": 8000, "channels": 1,
            "duration_ms": 4096, "peak_dbfs": -15.6, "speech_rms_dbfs": -29.0, "clipping_ratio": 0.0},
  "preprocessing": {"steps": ["DC_REMOVAL", "RESAMPLE"], "gain_db": 0.0, "telephone_band": false},
  "latency_ms": {"download": null, "decode": 0.07, "preprocess": 3.7, "asr": 61.6, "total": 120.6},
  "real_time_factor": 0.015,
  "warnings": ["NARROWBAND_SOURCE"]
}
```

Câu `STT_ID_04` ("Tôi tên Nguyễn Hoàng Minh.") ở dạng file 44,1 kHz stereo 24-bit, nhỏ hơn 25 dB:

| | Kết quả |
|---|---|
| `text` (tự khuếch đại +20 dB) | "TÔI TÊN NGUYỄN HOÀNG MINH", confidence 0,88 |
| `production.text` (như `/v1/calls` turn) | "TÔI SẼ NGHĨA VÀO BÊN", confidence 0,63 |

**Không gửi file nhiều câu vào route này.** Model nhận dạng cả clip một lần nên dễ mất chữ ở chỗ chuyển câu; file nhiều câu thì dùng `/v1/stt/transcribe`.

## 2. File dài nhiều câu — `/v1/stt/transcribe`

Gọi giống `/v1/stt/turn` (đổi `turn` thành `transcribe`). Khác biệt:

- **Tối đa 5 phút.**
- **VAD Silero cắt file thành từng câu**, nhận dạng từng câu rồi ghép text theo thứ tự thời gian. Response có thêm `segments[]`, mỗi phần tử gồm vị trí trong file, text và confidence của câu đó.
- **`compare`** trả `raw`: nguyên file, không tiền xử lý, không cắt theo VAD.
- **Thêm thông tin âm thanh:**
  - `audio.snr_db`: giọng to hơn nhiễu nền bao nhiêu dB.
  - `audio.speech_ms`: tổng thời gian có giọng.
  - `latency_ms.vad`: thời gian chạy VAD.
- **Thêm cảnh báo:** `LOW_SNR` và `NO_SPEECH_DETECTED`.

Ví dụ `segments`:

```jsonc
"segments": [
  {"start_ms": 14420, "end_ms": 18270, "text": "Ờ ANH LÀ NGUYỄN VĂN A NH", "confidence": 0.91},
  {"start_ms": 25460, "end_ms": 30870, "text": "ANH SINH NGÀY MƯỜI BỐN THÁNG BA NĂM MỘT CHÍN BẢY TÁM EM NHÉ", "confidence": 0.93}
]
```

## Đọc kết quả (chung cho hai chế độ)

**Model không tự tính WER.** PM tự so `text` với câu đúng. Model viết HOA, không có dấu câu, và đọc số thành chữ ("mười bốn" chứ không phải "14"), nên khi so hãy bỏ qua hoa/thường và dấu câu.

### `confidence`

- Là xác suất trung bình mà model gán cho các token nó đã chọn, từ 0 đến 1.
- Ở chế độ nhiều câu, `confidence` tổng là trung bình các câu, câu nhiều chữ có trọng số lớn hơn.
- Là `null` khi không có chữ nào, hoặc khi provider không trả con số này (Gemini, PhoWhisper).

**Confidence cao không có nghĩa là đúng.** Model có thể nghe nhầm mà vẫn rất tự tin: ngày 28/09, "hủy lịch" bị nghe thành "THÙY LINH" với xác suất các token là 0,79 / 0,98 / 0,57. Con số này chủ yếu giúp phát hiện chữ **bịa ra từ nhiễu hoặc khoảng lặng**, vì khi đó confidence thường thấp rõ rệt.

### `latency_ms`

| Trường | Ý nghĩa |
|---|---|
| `download` | Thời gian tải `audio_url` (`null` khi upload) |
| `decode` | Đọc file WAV |
| `preprocess` | Bỏ DC, resample, khuếch đại |
| `vad` | Chỉ có ở chế độ nhiều câu: tìm các đoạn có giọng |
| `asr` | Thời gian model nhận dạng — **con số chính để đánh giá tốc độ model** |
| `total` | Toàn bộ request phía server, gồm cả bản `production`/`raw` |

`real_time_factor = asr / thời lượng audio`. Ví dụ 0,05 nghĩa là model chạy nhanh gấp 20 lần thời gian thực. Server dùng chung CPU với cuộc gọi thật, nên số đo lúc đang có cuộc gọi sẽ cao hơn.

### `warnings`

| Cảnh báo | Nghĩa | Nên làm |
|---|---|---|
| `NARROWBAND_SOURCE` | File gốc chỉ 8 kHz (chất lượng điện thoại) | Bình thường với file ghi từ tổng đài; mất dải cao nên khó cải thiện |
| `CLIPPING` | Hơn 0,1% mẫu bị kịch trần (âm thanh bị méo) | Thu lại với mic nhỏ hơn: méo không sửa được |
| `LOW_LEVEL` | Giọng quá nhỏ (dưới −35 dBFS) | Đã tự khuếch đại, xem `gain_db`; nên thu lại to hơn |
| `LOW_SNR` (chỉ chế độ nhiều câu) | Giọng chỉ to hơn nhiễu nền dưới 10 dB | Kết quả kém là do môi trường thu, chưa chắc do model |
| `NO_SPEECH_DETECTED` (chỉ chế độ nhiều câu) | VAD không thấy giọng nói nào | Kiểm tra file; so với `raw` (compare=true) |

### Mã lỗi

Lỗi trả về dạng `{"detail": {"code": "...", "message": "..."}}`.

| HTTP | `code` | Khi nào |
|---|---|---|
| 401 | `BAD_KEY` | Thiếu hoặc sai API key |
| 404 | — | API chưa bật (`STT_EVAL_ENABLED=false`) |
| 413 | `AUDIO_TOO_LARGE` | File lớn hơn 25 MiB |
| 422 | `AUDIO_TOO_LONG` | Dài hơn 30 s (turn) hoặc 5 phút (nhiều câu) |
| 422 | `INVALID_WAV`, `EMPTY_AUDIO` | Không đọc được WAV, hoặc file rỗng |
| 422 | `URL_NOT_ALLOWED` | URL không phải http(s), hoặc trỏ tới địa chỉ nội bộ |
| 502 / 504 | `AUDIO_URL_FETCH_FAILED` / `AUDIO_URL_TIMEOUT` | Không tải được URL, hoặc tải quá 10 s |
| 500 | `STT_FAILED` | Model lỗi |

## Tiền xử lý: làm gì và vì sao

Không bước nào mô phỏng streaming: không có kết quả tạm thời (partial), mỗi clip hay mỗi câu chỉ được nhận dạng một lần. Mỗi bước được đo trên 40 câu golden (`eval/stt-bench`) trước khi giữ lại; bước nào làm kết quả tệ đi thì đã bị bỏ hoặc chỉnh lại.

| # | Bước | Turn | Nhiều câu | Vì sao |
|---|---|---|---|---|
| 1 | **Đọc nhiều định dạng WAV** | ✓ | ✓ | File xuất từ Audacity hay ffmpeg thường là 24-bit hoặc float, trước đây bị từ chối |
| 2 | **Trộn về mono** (trung bình các kênh) | ✓ | ✓ | Model chỉ nhận một kênh. File stereo có 2 người ở 2 kênh sẽ bị trộn lẫn; xem `audio.channels` |
| 3 | **Bỏ DC offset** | ✓ | ✓ | Mic rẻ hay làm lệch tín hiệu khỏi mức 0. Bộ trích đặc trưng của model đã tự bỏ phần này, nhưng phải bỏ trước thì mới đo đúng độ lớn và đỉnh ở bước 5 |
| 4 | **Resample một lần, thẳng về 16 kHz** (soxr chất lượng cao) | ✓ | ✓ | Model được huấn luyện ở 16 kHz. Resample thẳng giữ được dải 4–8 kHz, nơi có các phụ âm s/x/ch/th rất quan trọng với tiếng Việt (từ 29/09 `/v1/calls` cũng làm vậy, trước đó hạ về 8 kHz rồi mới nâng lại). Với file 8 kHz thì không lấy lại được (cảnh báo `NARROWBAND_SOURCE`) |
| 5 | **Khuếch đại clip quá nhỏ** (chỉ khi giọng dưới −35 dBFS; đưa về khoảng −26 dBFS; tối đa +20 dB; đỉnh không vượt −1 dBFS) | ✓ | ✓ | Clip thu nhỏ tiếng làm model đoán bừa. Đo được: clip nhỏ hơn 15–25 dB thì WER giảm từ 0,42–0,47 xuống 0,38. Clip đủ to thì **không** đụng tới, vì khuếch đại clip bình thường làm WER hơi tệ đi (0,39 → 0,40). Chỉ nhân một hằng số cho cả clip, không dùng nén/AGC vì chúng làm méo âm sắc theo thời gian |
| 5b | **Cổng im lặng**: Silero gắn cờ giọng dưới 200 ms **và** mức giọng của cả clip dưới −55 dBFS thì trả rỗng, không gọi model | ✓ | — | Clip chỉ có tiếng phòng (bộ PM, `B-SIL-01`, −67 dBFS) từng bị bước 5 khuếch đại +20 dB rồi model bịa ra "ĐÂY"; không khuếch đại thì vẫn bịa "Ừ". Không dùng **mỗi** Silero: trong tiếng đường phố SNR 6 dB, xác suất giọng của Silero không quá 0,31 nên câu thật bị bỏ (17/19 file ồn mạnh). Giọng nhỏ nhất của bộ PM (nói xa) ở −48,8 dBFS. Số đo: [evidence 02/10](../evidence/pm-preprocess-2026-10-02.md) |
| 6 | **Cắt đoạn bằng Silero VAD** (gộp các đoạn cách nhau dưới 0,7 s; đệm 1 s phía trước, 0,3 s phía sau) | — | ✓ | Bỏ khoảng lặng và nhiễu giữa các câu, vốn là nơi model hay "bịa chữ", và cho mốc thời gian từng câu. Đệm trước dài vì Silero phát hiện giọng chậm, và bỏ qua từ rất ngắn đứng ngay trước chỗ ngắt. Với một lượt nói thì bước này gần như không giúp gì (golden: 0,390 so với 0,392), nên chế độ turn không dùng |
| 7 | **Mỗi lần decode tối đa 30 s** | Giới hạn clip ≤ 30 s | Chia đoạn dài tại frame yên nhất | Bộ nhớ của model tăng theo bình phương độ dài: 30 s cần 0,6 GB, 90 s cần 3 GB, 180 s cần khoảng 12 GB. Không giới hạn thì một file 3 phút làm OOM cả server (đã xảy ra khi chạy thử 133 file LiveKit) |

**Kỹ thuật cố ý không dùng:**
- **Khử nhiễu (Krisp, GTCRN):** đo ngày 28/09 cho thấy WER **tệ hơn**, kể cả trên audio sạch ([evidence](../evidence/livekit-audio-plan-execution-2026-09-28.md)). Bộ khử nhiễu để lại dấu vết mà model chưa từng gặp lúc huấn luyện.
- **Lọc thông cao 100 Hz, khử nhiễu cổ điển (`noisereduce`), khử vang WPE, cắt đầu/đuôi theo VAD:** đo 02/10 trên bộ PM, thay đổi nhỏ và trái chiều, không đạt tiêu chí ([evidence](../evidence/pm-preprocess-2026-10-02.md)). Khử vang giúp câu nói xa nhưng làm hỏng câu ồn mạnh ở 8 kHz.
- **Pre-emphasis:** bộ trích đặc trưng của model đã tự làm; làm thêm là áp dụng hai lần.
- **AGC/compressor:** như đã nói ở bước 5.

**Kết quả trên 40 câu golden (mức âm bình thường):**

| Cách xử lý | WER | Số câu pass | Latency median |
|---|---|---|---|
| Như `/v1/calls` turn (không tiền xử lý) | 0,390 | 19/40 | 68 ms |
| `/v1/stt/turn` | 0,389 | 19/40 | 69 ms |
| `/v1/stt/transcribe` | 0,392 | 19/40 | 79 ms |

**Giới hạn đã biết:**
- Trên clip có mức âm bình thường, kết quả gần như giống hệt cách chạy của production. Lợi ích nằm ở clip nhỏ tiếng; riêng chế độ nhiều câu còn có lợi với file dài nhiều khoảng lặng và cho mốc thời gian.
- Chưa đo được lợi ích của bước 4 bằng số, vì bộ golden hiện chỉ có file 8 kHz.
