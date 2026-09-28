# Evidence: Phòng thủ chống nhận dạng sai do tiếng ồn cho LiveKit

**Ngày báo cáo:** 23/09/2026  
**Người thực hiện:** Phạm Tuấn Việt  
**Báo cáo đối chiếu:** `temp/baocao_22-09-2026_phan2_va_23-09-2026.md`

## 1. Mục tiêu và phạm vi

Tài liệu này ghi nhận các tệp mã nguồn, cấu hình, kiểm thử và tài liệu kỹ thuật liên quan trực tiếp đến hạng mục phòng thủ chống nhận dạng sai do tiếng ồn trong luồng gọi thoại LiveKit.

Phạm vi evidence bao gồm:

- Theo dõi nhiễu nền và tính tỷ lệ tín hiệu trên nhiễu (SNR).
- Lọc âm thanh trước khi chuyển vào ASR.
- Theo dõi độ ổn định của kết quả nhận dạng.
- Xác minh lượt nói và ngắt lời trước khi đưa vào hội thoại.
- Tích hợp và đánh giá Silero VAD.
- Giới hạn bộ đệm của ZipFormer khi âm thanh kéo dài liên tục.
- Đồng bộ cấu hình mô hình ASR trong Docker.

Các thay đổi về clinic mock, xử lý họ tên và các chức năng nghiệp vụ khác không thuộc phạm vi của evidence này.

## 2. Bằng chứng đáp ứng yêu cầu

| Yêu cầu                                        | Bằng chứng trong repository                                                                                                                                                                                                                                          |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Theo dõi nhiễu nền và SNR                      | `src/speech/audio/noise_tracker.py` định nghĩa `NoiseTracker` và `NoiseEvidence`; chỉ cập nhật mức nhiễu nền trên khung âm thanh được xác định không phải giọng nói.                                                                                                 |
| Lọc âm thanh trước ASR                         | `src/speech/asr/admission.py` định nghĩa `SpeechAdmission`, đánh giá VAD, SNR và thời lượng tối thiểu trước khi cho phép âm thanh vào ASR. `src/speech/asr/pipeline.py` tích hợp quyết định này tại luồng phân phối âm thanh và ghi nhật ký khi trạng thái thay đổi. |
| Phát hiện kết quả nhận dạng không ổn định      | `src/speech/asr/evidence.py` định nghĩa `TranscriptEvidenceTracker`, phân loại kết quả thành `CONVERGING`, `OSCILLATING` hoặc `UNKNOWN`.                                                                                                                             |
| Quyết định cuối trước khi chốt lượt nói        | `src/speech/turn/validator.py` định nghĩa `TurnValidator` với ba kết quả `ACCEPT`, `WAIT` và `DROP`. `src/speech/turn/controller.py` sử dụng kết quả này và chỉ cho phép `WAIT` khi vẫn còn khả năng nhận thêm dữ liệu.                                              |
| Không xác nhận ngắt lời khi chưa đủ bằng chứng | `src/speech/turn/interruption.py::_passes_gate()` chỉ xác nhận ngắt lời khi validator trả về `ACCEPT`; cả `WAIT` và `DROP` đều bị chặn tại thời điểm đánh giá.                                                                                                       |
| Sử dụng Silero cho lớp bằng chứng âm thanh     | `src/speech/asr/vad/silero.py` triển khai `SileroVadClassifier`. `src/speech/bundle.py::_build_noise_classifier()` tạo Silero VAD riêng cho `NoiseTracker`, không phụ thuộc VAD chính.                                                                               |
| Không chia sẻ trạng thái giữa các luồng VAD    | `src/speech/bundle.py` tạo các classifier riêng cho VAD chính, endpoint ASR, Speech Admission và Turn Validator.                                                                                                                                                     |
| Có thể lựa chọn VAD chính bằng cấu hình        | `src/speech/settings.py` hỗ trợ `vad_provider` gồm `energy`, `webrtc` và `silero`; `.env.example` mô tả `VAD_PROVIDER` và `SILERO_VAD_MODEL_PATH`.                                                                                                                   |
| Các lớp phòng thủ mặc định chưa kích hoạt      | `src/speech/settings.py` đặt `speech_admission_enabled=False` và `turn_validator_enabled=False`; cấu hình cho phép bật độc lập khi thử nghiệm.                                                                                                                       |
| Giới hạn bộ đệm ASR                            | `src/inference/asr/config.py` định nghĩa `ZIPFORMER_MAX_TURN_SPEECH_MS`; `src/inference/asr/providers/zipformer.py` cưỡng bức chốt và làm mới bộ đệm khi đạt ngưỡng.                                                                                                 |
| So sánh Silero VAD với VAD hiện tại            | `eval/vad-bench/compare_silero_webrtc.py` là công cụ chạy đối chiếu trên dữ liệu ghi âm thực tế.                                                                                                                                                                     |
| Đồng bộ mô hình ASR khi đóng gói               | `Dockerfile` tải mô hình `g-group-ai-lab/gipformer1.5-68M-rnnt`; `docker-compose.yml` và `docker-compose.prod.yml` trỏ các biến `ZIPFORMER_*_PATH` đến đúng các tệp trong image.                                                                                     |
| Sẵn sàng khởi tạo Silero trong Docker          | `Dockerfile` tải `silero_vad.onnx` và cài extra `vad-silero`; `docker-compose.yml` và `docker-compose.prod.yml` thiết lập `SILERO_VAD_MODEL_PATH` tới asset trong image.                                                                                            |

## 3. Danh sách tệp thay đổi theo hạng mục

### 3.1. Thành phần phòng thủ mới

| Tệp                                 | Trạng thái | Nội dung thay đổi                                                                              |
| ----------------------------------- | ---------- | ---------------------------------------------------------------------------------------------- |
| `src/speech/audio/noise_tracker.py` | Thêm mới   | Theo dõi mức nhiễu nền bằng trung bình động và cung cấp bằng chứng RMS/SNR.                    |
| `src/speech/asr/admission.py`       | Thêm mới   | Chặn sớm âm thanh có SNR thấp, thời lượng chưa đủ hoặc không phải giọng nói.                   |
| `src/speech/asr/evidence.py`        | Thêm mới   | Theo dõi chuỗi kết quả ASR tạm thời để nhận biết hội tụ và dao động bất thường.                |
| `src/speech/turn/validator.py`      | Thêm mới   | Tổng hợp bằng chứng âm thanh và độ ổn định để quyết định chấp nhận, chờ hoặc loại bỏ lượt nói. |
| `src/speech/asr/vad/silero.py`      | Thêm mới   | Tích hợp Silero VAD qua `sherpa-onnx`, bao gồm xử lý lại tần số lấy mẫu và cửa sổ âm thanh.    |

### 3.2. Tích hợp vào luồng xử lý hiện có

| Tệp                                        | Trạng thái     | Nội dung thay đổi                                                                                                                                              |
| ------------------------------------------ | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/speech/asr/pipeline.py`               | Chỉnh sửa      | Kết nối Speech Admission, NoiseTracker và TranscriptEvidenceTracker vào luồng âm thanh/ASR; chuyển bằng chứng sang Turn Controller và Interruption Controller. |
| `src/speech/turn/controller.py`            | Thêm mới       | Áp dụng Turn Validator trước khi phát sự kiện hoàn tất lượt nói; xử lý `WAIT` theo điều kiện còn hay hết cơ hội nhận dữ liệu.                                  |
| `src/speech/turn/interruption.py`          | Thêm/chỉnh sửa | Áp dụng cùng bằng chứng cho luồng ngắt lời; sửa lỗi coi `WAIT` tương đương `ACCEPT`.                                                                           |
| `src/speech/bundle.py`                     | Chỉnh sửa      | Khởi tạo các lớp phòng thủ theo cấu hình và tạo classifier độc lập cho từng consumer.                                                                          |
| `src/speech/settings.py`                   | Chỉnh sửa      | Bổ sung cấu hình VAD, Speech Admission, Turn Validator và đường dẫn mô hình Silero.                                                                            |
| `src/inference/asr/config.py`              | Chỉnh sửa      | Bổ sung ngưỡng thời lượng giải mã tối thiểu và thời lượng nói liên tục tối đa.                                                                                 |
| `src/inference/asr/providers/zipformer.py` | Chỉnh sửa      | Bỏ qua đoạn âm thanh quá ngắn và cưỡng bức làm mới bộ đệm khi lượt nói kéo dài quá ngưỡng.                                                                     |

### 3.3. Cấu hình, phụ thuộc và triển khai

| Tệp                       | Trạng thái | Nội dung thay đổi                                                                                                    |
| ------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------- |
| `.env.example`            | Chỉnh sửa  | Mô tả `VAD_PROVIDER`, `SILERO_VAD_MODEL_PATH`, các ngưỡng phòng thủ và giới hạn bộ đệm ZipFormer.                    |
| `pyproject.toml`          | Chỉnh sửa  | Bổ sung nhóm phụ thuộc cho WebRTC VAD, Silero VAD và LiveKit.                                                        |
| `Dockerfile`              | Chỉnh sửa  | Chuyển mô hình ASR sang `gipformer1.5-68M-rnnt`; tải `silero_vad.onnx` và cài dependency `vad-silero`.              |
| `docker-compose.yml`      | Chỉnh sửa  | Đồng bộ đường dẫn mô hình ASR và mô hình Silero cho môi trường Docker cục bộ.                                        |
| `docker-compose.prod.yml` | Chỉnh sửa  | Đồng bộ đường dẫn mô hình ASR và mô hình Silero cho môi trường production.                                          |

### 3.4. Công cụ đánh giá và tài liệu

| Tệp                                       | Trạng thái     | Nội dung thay đổi                                                                 |
| ----------------------------------------- | -------------- | --------------------------------------------------------------------------------- |
| `eval/vad-bench/compare_silero_webrtc.py` | Thêm mới       | So sánh kết quả phát hiện giọng nói giữa Silero và WebRTC trên các tệp ghi âm.    |
| `docs/reference/livekit-architecture.md`  | Thêm mới       | Mô tả kiến trúc LiveKit, các lớp phòng thủ và giới hạn bộ đệm ASR.                |
| `docs/reference/livekit-merge-to-main.md` | Thêm/chỉnh sửa | Ghi nhận cấu hình hợp nhất và trạng thái đóng gói mô hình Silero.                |

### 3.5. Kiểm thử liên quan

| Tệp                                        | Phạm vi xác minh                                                                    |
| ------------------------------------------ | ----------------------------------------------------------------------------------- |
| `tests/speech/audio/test_noise_tracker.py` | Cập nhật mức nhiễu nền và tính SNR.                                                 |
| `tests/speech/test_admission.py`           | Quyết định chấp nhận hoặc từ chối âm thanh theo SNR và thời lượng.                  |
| `tests/speech/test_evidence.py`            | Nhận biết transcript hội tụ, dao động và chưa đủ bằng chứng.                        |
| `tests/speech/test_pipeline_admission.py`  | Chặn âm thanh SNR thấp trước ASR và giữ hành vi cũ khi tính năng tắt.               |
| `tests/speech/test_pipeline_evidence.py`   | Truyền bằng chứng từ pipeline tới bộ điều khiển lượt nói.                           |
| `tests/speech/test_pipeline_validator.py`  | Chặn lượt nói giả trong toàn bộ pipeline và xác minh các tracker hoạt động độc lập. |
| `tests/speech/turn/test_validator.py`      | Bao phủ các quyết định `ACCEPT`, `WAIT` và `DROP`.                                  |
| `tests/speech/turn/test_controller.py`     | Xác minh cách Turn Controller xử lý validator, bao gồm `WAIT` ở cơ hội cuối.        |
| `tests/speech/turn/test_interruption.py`   | Tái hiện ngắt lời giả; xác minh `WAIT` không còn được coi là chấp nhận ngắt lời.    |
| `tests/speech/test_zipformer_stream.py`    | Bỏ qua đoạn quá ngắn, cưỡng bức flush và giới hạn kích thước bộ đệm.                |
| `tests/speech/vad/test_silero.py`          | Xác minh Silero VAD trên âm thanh giọng nói, im lặng và nhiễu.                      |

## 4. Luồng xử lý sau thay đổi

```text
Âm thanh đầu vào
  -> VAD chính: phát hiện bắt đầu/kết thúc lượt nói
  -> NoiseTracker + Silero VAD: ước lượng nhiễu nền và SNR
  -> Speech Admission: chấp nhận hoặc chặn âm thanh trước ASR
  -> ASR: tạo kết quả tạm thời/kết quả cuối
  -> TranscriptEvidenceTracker: đánh giá hội tụ hoặc dao động
  -> Turn Validator:
       ACCEPT -> cho phép xử lý tiếp
       WAIT   -> chờ thêm dữ liệu ở luồng chốt lượt; không xác nhận ngắt lời
       DROP   -> loại bỏ kết quả
  -> Turn Controller hoặc Interruption Controller
  -> Luồng nghiệp vụ hội thoại
```

## 5. Commit đối chiếu

| Commit    | Nội dung liên quan                                                                   |
| --------- | ------------------------------------------------------------------------------------ |
| `c6a88f3` | Bổ sung VAD streaming, Silero VAD và bộ điều khiển lượt nói.                         |
| `afabd20` | Kết nối ASR streaming vào LiveKit, bổ sung giới hạn bộ đệm và tích hợp pipeline.     |
| `09a2bc6` | Bổ sung công cụ benchmark STT/VAD.                                                   |
| `d1f36fd` | Bổ sung các lớp phòng thủ nhiều tầng và kiểm thử tương ứng.                          |
| `8cd6536` | Sửa luồng ngắt lời không được coi `WAIT` là `ACCEPT`; cập nhật cấu hình và tài liệu. |
| `ccd1163` | Đồng bộ mô hình ASR trong Docker sang `gipformer1.5`.                                |

## 6. Kết quả xác minh

Theo báo cáo công việc, toàn bộ gần 2.000 trường hợp kiểm thử tự động đã đạt sau khi hoàn tất các thay đổi.

Khi lập evidence, nhóm kiểm thử liên quan được chạy lại trong môi trường dự án bằng lệnh:

```bash
uv run --extra dev --extra speech pytest -q \
  tests/speech/audio/test_noise_tracker.py \
  tests/speech/test_admission.py \
  tests/speech/test_evidence.py \
  tests/speech/test_pipeline_admission.py \
  tests/speech/test_pipeline_evidence.py \
  tests/speech/test_pipeline_validator.py \
  tests/speech/turn/test_validator.py \
  tests/speech/turn/test_controller.py \
  tests/speech/turn/test_interruption.py \
  tests/speech/test_zipformer_stream.py \
  tests/speech/vad/test_silero.py
```

Kết quả tại thời điểm lập evidence: **101 test đạt**, không có test thất bại; pytest ghi nhận một cảnh báo deprecation từ `starlette.testclient`.

## 7. Tồn tại và lưu ý

- Các ngưỡng SNR, thời lượng tối thiểu và ngưỡng phát hiện dao động cần tiếp tục được hiệu chỉnh trên dữ liệu thực tế đa dạng hơn.
- Silero chưa được chọn làm VAD mặc định của toàn hệ thống.
- Mô hình Silero và dependency đã được đóng gói; việc chuyển `VAD_PROVIDER=silero` thành mặc định vẫn cần dựa trên kết quả kiểm thử end-to-end.
- `.env.example` đang có thay đổi cục bộ bổ sung cấu hình ElevenLabs Realtime STT. Phần thay đổi này không thuộc phạm vi báo cáo phòng thủ tiếng ồn và không được dùng làm bằng chứng cho hạng mục trên.
