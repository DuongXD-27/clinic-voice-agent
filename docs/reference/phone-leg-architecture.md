# Kiến trúc điện thoại thật với ASR self-host (ZipFormer)

Tài liệu này giải thích **cụ thể luồng dữ liệu** khi bot nghe/gọi một cuộc điện thoại thật (không phải đường HTTP chấm điểm của harness, đã nói ở [stt-flow.md](stt-flow.md)), dùng ZipFormer tự host làm ASR. Viết cho người chưa quen thuật ngữ viễn thông — có bảng giải nghĩa trước, sau đó đi từng bước một, mỗi bước ghi rõ **ai gửi, gửi gì, định dạng gì, bạn code hay dùng bên thứ ba**.

## 0. Bảng thuật ngữ (đọc trước, dùng để tra lại)

| Thuật ngữ | Nghĩa đơn giản |
|---|---|
| **PSTN** | Mạng điện thoại truyền thống (Public Switched Telephone Network) — thứ nối điện thoại di động/bàn của người gọi tới hệ thống bạn |
| **SIP** | Giao thức "bắt tay" cuộc gọi — ai gọi ai, đồng ý dùng codec nào, khi nào cúp máy. **Không mang âm thanh**, chỉ mang tín hiệu điều khiển |
| **RTP** | Giao thức mang **âm thanh thật** sau khi SIP đã thiết lập xong cuộc gọi — luồng gói tin nhỏ liên tục (đã nói ở câu hỏi trước: ~20ms/gói) |
| **SIP Trunk** | Dịch vụ bạn *mua* từ nhà mạng (Viettel, VNPT, Stringee, Twilio...) để nối server của bạn vào PSTN. Bạn không tự làm cái này |
| **Codec (G.711 μ-law/A-law)** | Cách nén/mã hoá từng sample âm thanh để truyền qua RTP. Là chuẩn cũ, đơn giản, 8kHz |
| **PCM** | Dữ liệu âm thanh số ở dạng "thô" nhất — một dãy số nguyên liên tiếp đại diện biên độ sóng âm theo thời gian. Sau khi giải mã codec, bạn luôn làm việc với PCM |
| **WebRTC** | Giao thức truyền âm thanh/video thời gian thực hiện đại (dùng trong trình duyệt, Zoom, Google Meet...). LiveKit xây trên nền này |
| **Streaming ASR** vs **Batch/Offline ASR** | Streaming: model nhận từng mẩu audio nhỏ liên tục, trả kết quả dần dần, "nhớ" ngữ cảnh giữa các lần gọi. Batch: phải đưa nguyên một đoạn hoàn chỉnh mới ra kết quả (Whisper/PhoWhisper đang thuộc loại này) |
| **Encoder (trong ZipFormer)** | *Khác* nghĩa với "mã hoá codec" ở trên — đây là phần mạng neural biến sóng âm thành biểu diễn số học để model "hiểu". ZipFormer's encoder chạy theo từng chunk nhỏ, không cần đợi hết câu |
| **Endpointing** | Model/hệ thống tự phát hiện "người dùng đã nói xong một câu" — ở ASR streaming thật, việc này có thể nằm ngay trong ASR, không cần VAD riêng |
| **ONNX** | Định dạng file model đã "đóng gói" để chạy suy luận (inference) nhanh, nhẹ, không cần cả framework train (PyTorch) nặng nề. ZipFormer thường được export sang ONNX để triển khai |
| **sherpa-onnx** | Phần mềm mã nguồn mở (cùng nhóm phát triển ZipFormer, dự án "Next-gen Kaldi"/k2) dùng để **chạy** model ZipFormer dạng ONNX — hỗ trợ cả `OnlineRecognizer` (streaming, cần checkpoint export đúng kiểu) lẫn `OfflineRecognizer` (batch, checkpoint nào cũng nạp được). Đây là thứ bạn sẽ dùng để serve model, không phải tự viết vòng lặp suy luận |
| **gRPC / WebSocket** | Hai cách hai chương trình nói chuyện qua mạng, giữ kết nối mở liên tục — phù hợp để đẩy audio + nhận text liên tục, khác với HTTP request/response một lần (kiểu harness đang dùng) |
| **Chunk/Frame** | Một lát cắt nhỏ, thời lượng cố định (ví dụ 10-20-30ms) của luồng audio liên tục |
| **Barge-in** | Người gọi ngắt lời bot giữa chừng — hệ thống phải dừng phát audio bot ngay lập tức |

## 1. Toàn cảnh: ai gửi gì cho ai

```
Người gọi (điện thoại)
   │  giọng nói qua sóng/dây
   ▼
[Bên thứ 3] Nhà mạng viễn thông (PSTN)
   │  SIP (báo hiệu) + RTP (âm thanh: G.711, gói ~20ms, 8kHz)
   ▼
[Bên thứ 3] SIP Trunk bạn thuê (Stringee/Viettel/VNPT/Twilio...)
   │  cùng giao thức SIP/RTP, chuyển tiếp qua Internet tới server bạn
   ▼
[Bên thứ 3 — bạn tự host, KHÔNG tự viết] LiveKit Agents (hoặc Pipecat)
   │  bóc SIP/RTP, giải mã G.711 → PCM sạch, chống rung/mất gói (jitter buffer),
   │  chia audio thành chunk đều đặn, đưa qua callback/async generator
   ▼
[Bạn code] Application code của bạn — nhận chunk PCM liên tục
   │  đẩy từng chunk vào ASR
   ▼
[Bên thứ 3 phần mềm, tự host] sherpa-onnx chạy model ZipFormer
   │  trả partial text (chưa chắc) + final text (chốt câu) liên tục
   ▼
[Bạn code] Core Agent (orchestrator, dialogue, FSM — đã có trong src/callbot/engine/)
   │  nhận final text, xử lý, quyết định câu trả lời
   ▼
[Bạn code] TTS (Text-to-Speech) sinh audio trả lời
   ▼
[Bên thứ 3 — tự host] LiveKit Agents phát audio ngược lại vào RTP
   ▼
[Bên thứ 3] SIP Trunk → PSTN → điện thoại người gọi
```

Ba nhóm rõ rệt:
- **Hoàn toàn bên thứ 3, không đụng vào**: nhà mạng, SIP Trunk — mua dịch vụ, cấu hình, không viết code.
- **Bên thứ 3 nhưng bạn tự host và cấu hình**: LiveKit Agents (hoặc Pipecat) để xử lý SIP/RTP, và sherpa-onnx để chạy ZipFormer. Đây là phần mềm mã nguồn mở bạn triển khai trên máy chủ của mình, nhưng **không tự viết lại logic RTP hay logic suy luận model** — quá rủi ro và không cần thiết khi đã có sẵn.
- **Bạn code thật sự**: keo nối các phần trên với nhau (nhận chunk từ LiveKit → đẩy vào sherpa-onnx → nhận text → đẩy vào Core Agent), và toàn bộ Core Agent (dialogue, policy, extraction — phần cốt lõi nghiệp vụ, không ai làm hộ được).

## 2. Vì sao không tự viết phần SIP/RTP

RTP nghe đơn giản (chỉ là gói UDP chứa byte âm thanh), nhưng thực tế xử lý đúng cần: đồng bộ timestamp, xử lý gói đến trễ/mất/sai thứ tự (jitter buffer), thương lượng codec qua SDP, xuyên NAT, DTMF (bấm phím), giữ máy/chuyển máy... Đây là lý do hợp đồng (Appendix B.2) liệt kê LiveKit Agents/Pipecat như điểm khởi đầu gợi ý thay vì tự viết. LiveKit SIP là cầu nối: một đầu nói SIP/RTP truyền thống với nhà mạng, đầu kia đưa ra audio sạch cho code bạn qua API hiện đại (WebRTC nội bộ, nhưng bạn không cần biết chi tiết WebRTC — chỉ cần dùng SDK Agents của họ).

**Việc bạn cần làm ở lớp này**: cấu hình LiveKit (tài khoản, số điện thoại, trunk), viết một "agent" nhỏ theo SDK của họ — về bản chất là một hàm callback nhận audio, y hệt như `STTPipeline.stream(frames: AsyncIterator[bytes])` đã có sẵn khung ở [pipeline.py:43-49](../../src/speech/asr/pipeline.py#L43-L49). `frames` chính là thứ LiveKit đưa cho bạn.

## 3. ZipFormer qua sherpa-onnx: gửi gì, nhận gì, khác PhoWhisper thế nào

> **Cập nhật sau khi kiểm chứng thật (Phase 0, xem `temp/plan_mvp_zipformer.md`)**: đoạn dưới đây mô tả ZipFormer *như một kiến trúc* — kiến trúc này CÓ THỂ được train/export để streaming thật. Nhưng file model cụ thể `hynt/ZipFormer-150M-CR-CTC-RNNT-6000h` (bản người dùng chọn) đã được test trực tiếp và **không phải bản streaming** — xem §3.1 ngay dưới đây trước khi đọc phần lý thuyết.

### 3.1 Sự thật đã kiểm chứng trên model cụ thể `hynt/ZipFormer-150M-CR-CTC-RNNT-6000h`

Nạp thử bằng `sherpa_onnx.OnlineRecognizer.from_transducer(...)` (API dành cho streaming) báo lỗi:

```
online-zipformer2-transducer-model.cc:InitEncoder:116 'encoder_dims' does not exist in the metadata
```

Nghĩa là file `.onnx` này **thiếu metadata streaming** (chunk size, cache dims...) mà sherpa-onnx cần để chạy incremental. Thử cả bản int8 lẫn bản fp32 gốc đều thiếu như nhau — không phải do quantize làm mất dữ liệu, mà bản thân file export ra vốn không phải bản streaming. Nạp lại bằng `sherpa_onnx.OfflineRecognizer.from_transducer(...)` (API batch) thì **chạy được ngay**, và cho kết quả tốt trên CPU thuần (không cần GPU):

| Audio test | Thời lượng | Thời gian xử lý | RTF |
|---|---|---|---|
| 0.wav | 3.74s | 0.11s | 0.030 |
| 1.wav | 2.40s | 0.07s | 0.029 |
| 2.wav | 1.55s | 0.05s | 0.032 |

(RTF = thời gian xử lý / thời lượng audio; RTF 0.03 nghĩa là nhanh hơn ~30 lần thời gian thực, chỉ dùng 2 luồng CPU, không GPU. Model nạp trong 1.8s.) Test thêm bằng cách giả lập audio 8kHz điện thoại (hạ tần rồi nâng lại) cho **kết quả transcript giống hệt** — dấu hiệu tốt, dù đây chỉ là 3 clip ngắn, giọng đọc rõ (không phải audio điện thoại thật với nhiễu đường dây, giọng nói tự nhiên ngập ngừng).

**Kết luận thực tế**: `hynt/ZipFormer-150M-CR-CTC-RNNT-6000h` hoạt động **giống PhoWhisper về cách vận hành** (đưa cả đoạn vào, nhận về một câu hoàn chỉnh — không có partial tăng dần), khác biệt là nó **nhanh hơn nhiều và có vẻ chính xác hơn cho tiếng Việt** theo số WER model tự công bố. Đây vẫn là lựa chọn tốt cho MVP, chỉ là không mang lại "phụ đề tăng dần khi đang nói" miễn phí như tôi mô tả ban đầu ở mục lý thuyết dưới đây. Nếu sau này thực sự cần partial thời gian thực, phải tìm/huấn luyện một checkpoint ZipFormer **được export riêng cho streaming** (sẽ nạp được bằng `OnlineRecognizer` không lỗi) — không phải checkpoint này.

### 3.2 Lý thuyết chung: ZipFormer streaming thật hoạt động khác PhoWhisper thế nào (áp dụng khi có checkpoint streaming thật)

Phần này mô tả cách một checkpoint ZipFormer **được export đúng cho streaming** sẽ hoạt động — hữu ích nếu sau này đổi sang checkpoint khác có hỗ trợ.

**Bạn gửi gì**: không gửi file, không gửi cả câu. Bạn liên tục đẩy **từng chunk PCM 16-bit** (ví dụ mỗi 100ms một lần, tuỳ cấu hình) vào một **phiên nhận dạng (streaming session)** mà sherpa-onnx giữ mở suốt cuộc gọi. Streaming session có trạng thái nội bộ (encoder cache) được cập nhật dần qua mỗi chunk, giống việc model "nghe liên tục" thay vì "nghe từng đoạn rồi quên".

**Bạn nhận gì**: sau mỗi vài chunk, session trả về partial hypothesis (câu đang hình thành, có thể còn đổi) rồi final segment khi endpointing xác định người nói đã dừng.

`speech/types.py` đã có sẵn kiểu dữ liệu đúng cho việc này — [`TranscriptEvent(text, is_final, confidence, start_ms, end_ms)`](../../src/speech/types.py#L26-L34), và [`TranscriptAggregator`](../../src/speech/asr/transcript.py) đã viết sẵn logic gộp partial/final thành `Transcript` hoàn chỉnh — vẫn hữu ích nếu sau này có checkpoint streaming thật.

### 3.3 So sánh cập nhật (dựa trên model thật đang có, không phải lý thuyết)

| | PhoWhisper (hiện có) | ZipFormer `hynt` (đã test) | ZipFormer streaming thật (lý thuyết, cần checkpoint khác) |
|---|---|---|---|
| Kiểu xử lý | Batch | **Batch** (không phải streaming như tưởng) | Streaming — chạy dần theo chunk |
| Cần VAD riêng để cắt đoạn? | Có, bắt buộc | Có, bắt buộc (giống PhoWhisper) | Không bắt buộc — model tự endpoint |
| Tốc độ (CPU, không GPU) | Chậm hơn, thường cần GPU để mượt | **RTF ~0.03, rất nhanh trên CPU thuần** | Tuỳ checkpoint |
| Độ trễ cảm nhận | Chờ hết câu + suy luận (có thể chậm) | Chờ hết câu, nhưng suy luận cực nhanh → cảm giác gần như tức thời dù không phải streaming thật | Có partial ngay khi đang nói |
| Runtime | `transformers.pipeline` (PyTorch) | `sherpa-onnx` (C++, nhẹ) | `sherpa-onnx` |

## 4. Câu hỏi chính: 2 server gọi nhau qua API, hay 1 server nhiều service?

Đây là quyết định kiến trúc thật, không có đáp án tuyệt đối — nhưng dự án của bạn **đã có tiền lệ** cho câu trả lời.

### Nhìn vào cái đã làm: Clinic Mock

Mở [docker-compose.yml](../../docker-compose.yml): `bot` (Core Agent) và Clinic Mock là **hai service tách biệt**, `bot` gọi Clinic Mock qua HTTP (`CLINIC_MOCK_BASE_URL`). Đây chính là mô hình "2 server gọi nhau qua API" — đã được chọn và đang chạy tốt cho phần nghiệp vụ.

### Áp dụng cho ASR: nên tách, nhưng tách "nhẹ" — cùng máy, khác process

**Lý do nên tách ASR ra thành service riêng (không nhét vào chung process với Core Agent):**

1. **sherpa-onnx đã có sẵn server dựng riêng** (ví dụ dạng WebSocket streaming server đi kèm dự án sherpa-onnx) — bạn chạy nó như một service độc lập, gần như không cần viết code serve model. Nếu nhét vào chung process với Core Agent, bạn phải tự viết lại phần quản lý nhiều phiên streaming đồng thời (mỗi cuộc gọi một session ASR) — việc mà server có sẵn đã làm.
2. **Đặc tính tài nguyên khác hẳn nhau**: ASR streaming cần chạy liên tục, ăn CPU/GPU đều đặn theo số cuộc gọi đang mở. Core Agent (dialogue, gọi LLM, gọi Clinic Mock) chủ yếu chờ I/O (network), ít tốn CPU tại chỗ. Tách ra để scale riêng — ví dụ tăng máy chạy ASR khi nhiều cuộc gọi đồng thời, mà không cần nhân bản Core Agent.
3. **Cô lập lỗi**: ASR service crash không kéo sập luôn phiên dialogue đang xử lý các cuộc gọi khác đang ở bước "text mode" hay đang chờ Clinic Mock.
4. **Nhất quán với thói quen đã chọn trong dự án** (Clinic Mock đã tách kiểu này) — dễ vận hành hơn vì đội ngũ đã quen mô hình "mỗi thành phần một container, gọi nhau qua API nội bộ", thấy trong `docker-compose.yml`.

**Nhưng "tách" ở đây nghĩa là gì cụ thể:**

- Không cần "2 server" theo nghĩa hai máy vật lý khác nhau, hai nơi triển khai khác nhau. Vẫn có thể là hai container trên **cùng một máy** (giống `bot` + `postgres` + Clinic Mock hiện tại đều khai báo trong cùng một `docker-compose.yml`), giao tiếp qua mạng nội bộ (WebSocket/gRPC tới `sherpa-onnx:6006` kiểu địa chỉ nội bộ docker, không phải qua Internet).
- Độ trễ thêm do network hop nội bộ (cùng máy hoặc cùng mạng LAN) là rất nhỏ (dưới 1ms thường), không đáng kể so với thời gian model suy luận — không phải lý do để ngại tách.

**Khi nào nên gộp chung 1 process thay vì tách:** nếu bạn chỉ có một cuộc gọi tại một thời điểm (demo, thử nghiệm cá nhân, không cần chịu tải đồng thời) và muốn tối giản số thành phần cần dựng — lúc đó nhét ASR làm một thư viện gọi trực tiếp trong process Core Agent (giống cách `GeminiASR`/`PhoWhisperASR` đang được gọi trực tiếp, không qua network) là hợp lý, đỡ phải quản lý thêm một service. Đây là đánh đổi giữa đơn giản triển khai và khả năng chịu tải — với quy mô "tuần 6 demo, một cuộc gọi trực tiếp" theo hợp đồng (§1.3.1: chỉ cần chứng minh được một cuộc gọi sống, không phải chấm điểm theo tải), gộp chung có thể là lựa chọn đủ dùng và đỡ việc nhất trong ngắn hạn.

## 5. Bảng tóm tắt "code hay không code"

| Thành phần | Bạn tự viết? | Ghi chú |
|---|---|---|
| Kết nối PSTN, SIP Trunk | Không | Mua dịch vụ, chỉ cấu hình |
| Giải mã SIP/RTP, jitter buffer, NAT | Không | Dùng LiveKit Agents/Pipecat |
| Model ZipFormer (kiến trúc, huấn luyện) | Không | Dùng checkpoint có sẵn (`hynt/ZipFormer-150M` hoặc tương đương) |
| Runtime chạy ZipFormer | Không (dùng sherpa-onnx) | Tự host, tự triển khai, nhưng không tự viết vòng lặp suy luận. `hynt/ZipFormer-150M` đã kiểm chứng chỉ nạp được qua `OfflineRecognizer` (batch), không phải `OnlineRecognizer` — xem §3.1 |
| Đóng gói ASR thành service riêng (nếu chọn tách) | Có, nhưng ít — chủ yếu cấu hình + Dockerfile | |
| Cầu nối "frame audio (VAD cắt đoạn) → gửi vào sherpa-onnx → nhận text → đẩy vào Core Agent" | **Có, đây là phần việc thật của bạn** | Với checkpoint `hynt` hiện tại, tương đương cách `PhoWhisperASR.transcribe()` đã hoạt động, không phải `STTPipeline.stream()` |
| VAD (để cắt đoạn trước khi gọi model) | Có thể tái dùng `vad/streaming.py` đã có | **Bắt buộc** với checkpoint `hynt` hiện tại (batch, không tự endpoint) |
| Core Agent (dialogue, FSM, extraction, policy) | **Có, toàn bộ** | Đã có trong `src/callbot/engine/`, không đổi bất kể chọn ASR nào |
| TTS phát lại | Có (tích hợp provider) | Dùng OpenAI TTS cho demo |

---

**Tóm gọn:** bạn không tự viết phần viễn thông (SIP/RTP) hay phần lõi suy luận ASR (ZipFormer/sherpa-onnx) — cả hai dùng phần mềm/mô hình có sẵn, tự host. Việc thật sự phải code là (1) lớp keo nối các mảnh có sẵn lại theo đúng thứ tự dữ liệu chảy (bao gồm VAD cắt đoạn trước khi gọi model, vì checkpoint `hynt` đã kiểm chứng là batch, không tự endpoint), và (2) toàn bộ Core Agent nghiệp vụ. Về cách bố trí: nên tách ASR thành service riêng gọi qua API nội bộ (HTTP/gRPC) — giống hệt cách Clinic Mock đã tách trong dự án này — vì đặc tính tài nguyên khác Core Agent; gộp chung một process chỉ hợp lý nếu bạn cố tình tối giản cho demo một cuộc gọi duy nhất.

**Cập nhật quan trọng sau kiểm chứng thật (xem §3.1):** `hynt/ZipFormer-150M-CR-CTC-RNNT-6000h` không phải checkpoint streaming — nó chạy ở chế độ batch giống PhoWhisper, chỉ khác là nhanh hơn nhiều (RTF ~0.03 trên CPU thuần) và có vẻ chính xác hơn cho tiếng Việt. Điều này không phủ nhận lựa chọn dùng ZipFormer cho MVP — chỉ là kỳ vọng "phụ đề tăng dần khi đang nói" cần một checkpoint khác, export riêng cho streaming, nếu sau này thực sự cần.
