# Evidence: TTS — Dự phòng khi Vbee lỗi trên cuộc gọi thời gian thực (01/10, tuần 3)

## Mục tiêu

Sau task 30/09, `SpeechSynthesizer.synthesize_stream` gọi thẳng `VbeeTTS.synthesize_stream` và bỏ qua gateway. Hệ quả là trên đường LiveKit (Đường B), **Vbee lỗi thì bot im**, không chuyển sang ElevenLabs như đường HTTP.

Task này đưa stream đi qua `TTSGateway` và đặt luật dự phòng:
- Vbee lỗi **trước chunk đầu**: ElevenLabs đọc **đúng câu đó**.
- Lỗi khi **đã phát một phần**: dừng, không đọc lại từ đầu, vì đọc lại sẽ lặp câu và audio khác `utterance` (§4.1.3).

Đây là điều kiện để nhánh `feature/tts-w3-vbee-streaming` merge được.

Kế hoạch: `docs/plans/tts-w3-w6.md`, mục T5 01/10 "Đường B — Dự phòng khi Vbee lỗi trên cuộc gọi thời gian thực". Làm ngày 02/10, trễ 1 ngày so với plan.

## Kết luận

Đường B có lại dự phòng ElevenLabs, với luật giống đường HTTP nhưng phù hợp với stream:

| Tình huống | Kết quả |
|---|---|
| Vbee lỗi trước chunk đầu (503, 429, timeout, không nối được, câu > 300 ký tự…) | ElevenLabs đọc đúng câu đó. Log WARNING "chuyển sang elevenlabs", cùng mẫu với HTTP nên đếm tỉ lệ fallback chung được |
| Vbee lỗi khi đã phát một phần | Dừng, **không** gọi ElevenLabs, **không ném lỗi**. Bot hụt nửa câu nhưng cuộc gọi tiếp tục. Log WARNING "lỗi giữa câu… dừng, không đọc lại"; mã lỗi ghi vào `error_code` |
| Cả Vbee và ElevenLabs lỗi trước chunk đầu | Ném lỗi của ElevenLabs. `CallBridge` xử lý như trước task này: lỗi bung ra khỏi `run()`, cuộc gọi kết thúc |
| Khách nói chen (`cancel()`) | Dừng provider **đang chạy**, Vbee hoặc ElevenLabs. Lỗi đọc do chính `cancel()` đóng kết nối không bị coi là lỗi, nên không chuyển dự phòng |

**Vì sao lỗi giữa câu thì dừng êm thay vì ném lỗi:** `CallBridge` để lỗi từ `_speak` bung ra khỏi `run()`, và điều đó kết thúc luôn cuộc gọi. Nếu Vbee rớt giữa câu mà ném lỗi, cả cuộc gọi bị cắt chỉ vì nửa câu. Dừng êm thì khách nghe hụt nửa câu, có thể hỏi lại, và cuộc gọi vẫn còn. Lỗi vẫn để lại dấu vết trong log WARNING và trong `last_stream.error_code`.

**Observability:** gateway giờ điền `TTSStreamInfo` (`provider_actual`, `voice`, `sample_rate`, `fallback_used`, `ttfa_ms`, `error_code`) và `CallBridge` đọc qua `last_stream_result`. Span `speech.tts.synthesize` của LiveKit có lại `voice` và `fallback_used` đúng (thiếu từ task 30/09).

`ttfa_ms` của span giờ là thời gian từ lúc gọi TTS tới khi chunk đầu đến bên phát. Đây đúng là TTFA khách nghe. Trước nhánh này, span lấy byte đầu của Vbee dù bot phải chờ đủ câu mới phát. `tts_cost` vẫn chưa ra số vì `config/tracing.yaml` chưa đặt giá TTS.

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| `TTSGateway.synthesize_stream`: lỗi trước chunk đầu → dự phòng đọc đúng câu đó, log không có text | `src/inference/tts/gateway.py`. Test `test_error_before_first_chunk_switches_to_fallback_for_same_sentence` (log có `http_503`, "chuyển sang elevenlabs", không có tên bệnh nhân), `test_rejected_text_also_falls_back` |
| Lỗi sau khi đã phát → dừng, không đọc lại | Test `test_error_mid_sentence_stops_without_replay` (chỉ có A, B; ElevenLabs không được gọi; `error_code` = `connection_failed`), `test_fallback_error_mid_sentence_stops_and_is_recorded` |
| Cả hai lỗi → ném lỗi | Test `test_both_fail_before_first_chunk_raises_fallback_error`, `test_no_fallback_configured_raises` |
| `TTSGateway.cancel()` gọi `cancel()` của provider đang chạy | Gateway nhớ provider đang phát (`_active`). Test `test_cancel_reaches_primary_and_does_not_fall_back`, `test_cancel_during_fallback_reaches_fallback_provider`, `test_error_after_cancel_does_not_switch_to_fallback`, `test_next_sentence_after_cancel_plays_normally` |
| Bên phát dừng sớm thì request tới provider đóng ngay | Các tầng stream lồng nhau bọc `contextlib.aclosing`: `CallBridge` bỏ vòng lặp thì request đóng ngay, không chờ GC. Test `test_consumer_stopping_early_closes_provider_stream_at_once` |
| `SpeechSynthesizer.synthesize_stream` / `cancel` đi qua gateway | `src/speech/bundle.py`: không còn gọi thẳng `provider.synthesize_stream`. Test `test_stream_falls_back_through_gateway_and_reports_actual_provider`, `test_vbee_stream_reaches_synthesizer_chunk_by_chunk_and_cancel_closes_it` |
| Sample rate hai provider khớp nhau trên stream | Cấu hình hiện tại: Vbee 8000 Hz, ElevenLabs `pcm_8000` = 8000 Hz, nên phát thẳng. Nếu provider thực tế khác tần số track, `SpeechSynthesizer` gom lại và resample **một lần** ở cuối câu (resample từng chunk rời sẽ có tiếng tách ở chỗ nối); đã hủy thì không phát phần gom. Test `test_stream_fallback_at_other_rate_is_resampled_once_to_track_rate` |
| Provider chỉ có `synthesize` vẫn chạy được trên stream | Gateway gọi `synthesize` trong thread, phát một khối, lấy sample rate từ kết quả. Test `test_sync_only_provider_streams_one_block_at_its_rate`, `test_sync_tts_stream_uses_gateway_fallback_at_track_rate` (test cũ, vẫn pass) |
| Test cũ của gateway (HTTP) vẫn pass | `tests/inference/tts/test_gateway_fallback.py` không sửa test cũ nào, pass |

**Kiểm với httpx thật** (không tốn quota): `VbeeTTS` thật trỏ vào server giả ở local, dự phòng là provider giả (script tạm, không commit).

| Server giả làm gì | Kết quả |
|---|---|
| Trả 503 ngay | Log `TTS vbee lỗi [TTSUnavailable http_503], chuyển sang elevenlabs`; nhận audio của dự phòng; `fallback_used=True` |
| Gửi 2 chunk rồi cắt kết nối giữa câu | Log `TTS vbee lỗi giữa câu [TTSUnavailable connection_failed], dừng, không đọc lại`; nhận đúng 2 chunk của Vbee, không có audio dự phòng; `error_code=connection_failed` |

## File liên quan

- `src/inference/tts/base.py`: `TTSStreamInfo`.
- `src/inference/tts/gateway.py`: `synthesize_stream`, `_provider_stream`, `cancel`, `last_stream`.
- `src/speech/bundle.py`: `SpeechSynthesizer.synthesize_stream` / `cancel` qua gateway, resample khi khác tần số.
- `src/inference/tts/providers/vbee.py`, `elevenlabs.py`, `openai.py`: thuộc tính `voice` (để trace có giọng thật).
- `tests/inference/tts/test_gateway_stream.py` (mới, 14 test; chạy 5 lần liên tiếp đều pass), `tests/speech/test_asr_tts_gateway.py` (thêm 2 test).

## Luồng hiện tại (Đường B)

```text
CallBridge._speak(text)
  -> SpeechSynthesizer.synthesize_stream(text)
  -> TTSGateway("vbee").synthesize_stream
       Vbee stream ──ok──> yield chunk ... (last_stream: vbee, voice, ttfa_ms)
         │ lỗi trước chunk đầu  -> WARNING "chuyển sang elevenlabs"
         │                         -> TTSGateway("elevenlabs").synthesize_stream(cùng câu)
         │                              ok -> yield chunk (fallback_used=True)
         │                              lỗi trước chunk đầu -> ném lỗi (CallBridge như cũ)
         │ lỗi khi đã phát      -> WARNING "lỗi giữa câu", dừng (error_code), không đọc lại
  -> CallBridge cắt frame 20 ms -> AudioSource

Khách nói chen: CallBridge.cancel() -> SpeechSynthesizer.cancel() -> TTSGateway.cancel()
  -> cancel() của provider đang chạy (Vbee: đóng request; ElevenLabs: đóng WebSocket)
```

Đường A (HTTP) không đổi: `TTSGateway.synthesize`.

## Quy trình xác minh

```powershell
$env:PYTHONUTF8 = "1"
python -m pytest tests/inference/tts tests/speech/test_asr_tts_gateway.py -q
python -m ruff check src tests
python -m ruff format --check src tests/inference/tts tests/speech/test_asr_tts_gateway.py
```

## Kết quả xác minh cục bộ (2026-10-02)

| Command | Kết quả |
| --- | --- |
| `python -m pytest tests/inference/tts tests/speech/test_asr_tts_gateway.py -q` | Pass (126 passed) |
| `python -m ruff check src tests` | Pass |
| `python -m ruff format --check` (các file trong task) | Pass |
| `python -m pytest -q` (với `PYTHONUTF8=1`) | Pass (3758 passed, 19 skipped) |

## Ghi chú

- **Sau khi merge và deploy** (CD deploy từ main): chạy benchmark "sau" ([benchmark-streaming-truoc-sau.md](benchmark-streaming-truoc-sau.md)). Lần chạy này vừa là kiểm hồi quy, vừa là số đo:
  - phần HTTP kiểm Đường A (turn latency ≤ 8 s, WAV đúng định dạng, không lượt nào chuyển ElevenLabs);
  - phần LiveKit gọi một cuộc thật trên Đường B, qua đường stream mới của gateway. Dự phòng chỉ chạy khi Vbee lỗi, nên lần chạy thường không kích hoạt nó.
- **Dự phòng chỉ bật khi cấu hình:** repo mặc định `tts_fallback_provider: null` (`config/speech.yaml`). Prod đã đặt `TTS_FALLBACK_PROVIDER=elevenlabs` trong `/opt/callbot/.env` từ 28/09 ([tts-audio-mode-prod.md](tts-audio-mode-prod.md)), nên deploy xong là có, không cần sửa `.env`.
- **Chưa thử dự phòng với ElevenLabs thật trên stream**, vì tốn quota ElevenLabs. Adapter ElevenLabs stream đã có test riêng (`tests/inference/tts/providers/test_elevenlabs*.py`) và đã chạy trên LiveKit thật khi còn là provider chính (trước khi prod chuyển sang Vbee ngày 28/09). Muốn kiểm thật thì dùng `bash bench/run.sh <nhãn> --profile full --parts tts`. Lệnh này cho Vbee trỏ vào cổng đóng, chỉ trong process benchmark, rồi đo TTFA khi ElevenLabs đọc thay (~226 ký tự ElevenLabs).
- **Lỗi giữa câu chỉ ghi log và `error_code`, chưa báo Engine.** Engine chưa biết khách chỉ nghe được nửa câu. Việc này cùng loại với "phần text đã phát" khi bị ngắt lời (task 07/10, thao tác 3 của barge-in), nên làm chung ở đó.
- **`CallBridge` chưa đọc `error_code`:** span vẫn ghi `result=OK` cho câu bị dừng giữa chừng. Muốn trace phân biệt được thì `CallBridge` cần đọc thêm trường này. Đây là sửa nhỏ ở transport, nên làm cùng task 07/10.
- **Ngân sách thời gian trường hợp xấu:** Vbee thường được chờ khoảng 3 s (`VBEE_TIMEOUT_S`; không nối được thì 1,5 s, `VBEE_CONNECT_TIMEOUT_S`) rồi mới chuyển ElevenLabs (3 s trên prod, `ELEVENLABS_TIMEOUT_S=3` trong `.env`; mặc định repo là 4 s), như đường HTTP. Đây không phải trần cứng: timeout của httpx tính cho từng lần đọc, còn trần tổng chỉ được kiểm khi có chunk về. Nếu Vbee trả header gần hết 3 s rồi chunk đầu cũng chậm gần 3 s nữa, khách có thể chờ lâu hơn 3 s. Đường HTTP trên main cũng vậy, không phải hồi quy. Trên Đường B, khách có thể im lặng chờ ~3 s, hoặc hơn trong trường hợp trên, trước khi nghe giọng dự phòng. Muốn ngắn hơn cho cuộc gọi realtime thì có thể đặt một trần riêng, thấp hơn, cho TTFA của stream. Chưa làm, cần chốt với PM.
