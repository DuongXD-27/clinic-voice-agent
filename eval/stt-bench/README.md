# STT evaluator skeleton

Evaluator này đọc trực tiếp `golden-cases.yaml`. Nó không chứa model STT và không gọi dịch
vụ STT bên ngoài.

## Validate dataset

```powershell
python eval/stt-bench/evaluate.py --validate-only
```

Lệnh này kiểm tra schema, duplicate ID, reference, đường dẫn audio và WAV theo
`audio_spec` (mono, 8000 Hz, PCM16). Nó không tạo scorecard và không gọi adapter.

## Score prediction JSONL

Mỗi dòng là một JSON object, bắt buộc có `id` và `text`; `latency_ms`, `is_final`, và
`metadata` là tùy chọn.

```json
{"id":"STT_ID_01","text":"Tôi là Nguyễn Văn A.","latency_ms":123}
```

```powershell
python eval/stt-bench/evaluate.py --predictions <file>
```

Prediction file phải chứa đúng một prediction cho mọi case và không được có ID lạ.

## Run an STT adapter later

Implement `STTAdapter`/`STTResult` từ `adapters/base.py`, rồi truyền một adapter instance,
class không cần argument, hoặc factory không cần argument dưới dạng `module:attribute`:

```powershell
python eval/stt-bench/evaluate.py --adapter <module:attribute>
```

Evaluator gọi `transcribe(audio_path)` tuần tự cho từng WAV. Có thể dùng `--model-name` và
`--results-dir` để đổi tên model hoặc nơi ghi output.

Mỗi lần score tạo một CSV chi tiết và một summary JSON trong `results/`.

## Scoring rules

- WER là diagnostic, gồm substitution/deletion/insertion; không có WER pass threshold.
- Critical entity error là business-critical và làm critical case FAIL. So khớp theo token
  đã bỏ punctuation/lowercase, nhưng không bỏ dấu, sửa tên, sửa DOB hay xóa phủ định.
- Với entity có dạng số nhưng gold reference viết hoàn toàn bằng chữ, evaluator chấp nhận
  nguyên reference chính xác; không dùng fuzzy number rewriting.
- Với `should_produce_text: false`, bất kỳ Unicode letter/number nào trong prediction đều là
  hallucination và case tự động FAIL. Whitespace hoặc punctuation-only được coi là empty.
- Latency chỉ được tổng hợp khi prediction/adapter trả về `latency_ms`.
- `expected_semantic` và `expected_signal` được validate/giữ làm metadata của golden case;
  evaluator không dùng LLM hay tự suy diễn semantic intent.
