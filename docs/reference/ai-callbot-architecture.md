# AI Callbot Vinmec — Kiến trúc và luồng hoạt động

Tài liệu mô tả **kiến trúc đích**  ngày 16/09/2026.

Mở file bằng trình xem Markdown hỗ trợ Mermaid để hiển thị sơ đồ.

## 1. Kiến trúc tổng thể

HTTP phục vụ chấm điểm; điện thoại phục vụ cuộc gọi thực. Cả hai dùng chung một lõi nghiệp vụ. Clinic Mock là nguồn duy nhất có thẩm quyền về trạng thái lịch hẹn.

```mermaid
flowchart TB
    HARNESS["Bộ kiểm thử — Harness"] <--> HTTP["HTTP Adapter — FastAPI<br/>Mở cuộc gọi và nhận từng lượt"]
    USER["Người gọi"] <--> TEL["Tổng đài / SIP"]
    TEL <--> PHONE["Phone Adapter<br/>Âm thanh hai chiều, ngắt lời"]

    HTTP --> INPUT{"Dữ liệu đầu vào"}
    PHONE --> INPUT
    INPUT -->|Audio| STT["Speech-to-Text<br/>Chuẩn hóa audio → VAD → ASR"]
    INPUT -->|Text| CORE
    STT -->|Transcript| CORE

    subgraph ENGINE["AI Callbot Engine"]
        CORE["Call Orchestrator<br/>Điều phối từng lượt"]
        SESSION["Session Manager + FSM<br/>Ngữ cảnh, trạng thái, bộ đếm"]
        IE["Information Extraction<br/>Ý định, tên, ngày sinh, đồng ý,<br/>khung giờ, tín hiệu cuộc gọi"]
        POLICY["Policy + Guardrails<br/>Tiếp tục, hỏi lại, chuyển máy<br/>hoặc kết thúc"]
        VERIFY["Identity Verifier<br/>Đối chiếu tên và ngày sinh"]
        DM["Dialogue Manager<br/>Chọn bước tiếp theo và lời thoại"]
        GW["Clinic Gateway<br/>Kiểm tra lệnh ghi<br/>Idempotency-Key, If-Match"]
        OUT["Output Guard<br/>Kiểm soát lời thoại đầu ra"]

        CORE <--> SESSION
        CORE --> IE --> POLICY --> DM
        DM <--> VERIFY
        VERIFY <--> GW
        DM <--> GW
        DM --> OUT
    end

    GW <-->|API nghiệp vụ| MOCK[("Clinic Mock<br/>Bệnh nhân, lịch hẹn, khung giờ")]
    OUT --> RESPONSE["Phản hồi<br/>utterance, state, ended, outcome"]
    OUT --> TTS["Text-to-Speech<br/>Đọc đúng nội dung utterance"]
    TTS --> AUDIO["Audio phản hồi<br/>audio_url hoặc luồng âm thanh"]
    RESPONSE --> HTTP
    AUDIO --> HTTP
    AUDIO --> PHONE
    CORE -.-> TRACE["Trace từng lượt<br/>Kiểm thử và truy vết"]
```

Các ranh giới trách nhiệm:

- **Session Manager** giữ trạng thái hội thoại và bản đọc tạm của dữ liệu cần thiết; không tạo kho trạng thái lịch hẹn độc lập.
- **Information Extraction** trích thông tin từ lời người gọi theo câu bot vừa hỏi; không nhận hồ sơ danh tính chuẩn để suy đoán câu trả lời.
- **Verifier** đối chiếu tên và ngày sinh; số điện thoại chỉ phục vụ tra cứu.
- **Policy và Gateway** kiểm soát quyết định và lệnh ghi. Nếu dùng LLM, LLM không được bỏ qua các kiểm soát này.
- **Output Guard** kiểm tra lời thoại trước khi gửi hoặc tổng hợp tiếng nói, đặc biệt với thông tin lịch hẹn và nội dung lâm sàng.
- **Phone Adapter** chuyển đổi tín hiệu điện thoại sang giao diện chung của lõi; việc chuyển máy thật cần tích hợp với tổng đài.

## 2. Một lượt hội thoại được xử lý như thế nào?

Sơ đồ mô tả lượt sau khi đã mở phiên. Các bước đọc/ghi Clinic Mock chỉ thực hiện khi nghiệp vụ cần.

```mermaid
sequenceDiagram
    autonumber
    participant A as HTTP / Phone Adapter
    participant S as Speech
    participant C as Orchestrator
    participant X as Session
    participant E as Extraction
    participant P as Policy
    participant D as Dialogue + Verifier
    participant G as Gateway
    participant M as Clinic Mock

    A->>C: call_id, lượt, dữ liệu người gọi
    C->>X: Nạp ngữ cảnh và trạng thái
    X-->>C: Câu hỏi trước, bộ đếm, hành động chờ
    alt Có audio
        C->>S: Chuẩn hóa audio, VAD, ASR
        S-->>C: Transcript
    else Có text
        Note over A,C: Dùng trực tiếp text
    end
    C->>P: Kiểm tra điều kiện và tín hiệu im lặng
    alt Có thể xử lý nội dung
        C->>E: Transcript + ngữ cảnh câu hỏi
        E-->>C: Thông tin trích xuất + nguồn gốc
        C->>P: Kiểm tra ngoại lệ và giới hạn
        P-->>C: Quyết định xử lý
        C->>D: Xử lý bước hội thoại theo quyết định
        opt Cần tra cứu hoặc thao tác nghiệp vụ
            D->>G: Yêu cầu đọc / ghi
            G->>G: Kiểm tra ràng buộc của thao tác
            G->>M: API nghiệp vụ, header phù hợp
            M-->>G: Dữ liệu hoặc lỗi
            G-->>D: Kết quả thao tác
        end
        D-->>C: Lời thoại, trạng thái, kết quả
    else Hỏi lại hoặc kết thúc do tín hiệu cuộc gọi
        C->>D: Thực thi quyết định Policy
        Note over D,M: Nếu cần ghi kết quả outbound, vẫn đi qua Gateway
        D-->>C: Phản hồi phù hợp
    end
    C->>C: Kiểm soát lời thoại đầu ra
    C->>X: Cập nhật phiên và ghi trace
    opt Chế độ audio
        C->>S: TTS từ đúng utterance
        S-->>C: Audio sẵn sàng phục vụ
    end
    C-->>A: utterance, audio, state, ended, outcome
```

Trong HTTP audio mode, `audio_url` phải sẵn sàng khi trả phản hồi và đọc đúng `utterance`. Hai endpoint chấm điểm phải phản hồi trong 8 giây; phép đo độ trễ của harness tính cả việc tải audio. Đây là yêu cầu hợp đồng, chưa phải kết quả đo của repo.

## 3. Luồng nghiệp vụ Inbound và Outbound

Hai luồng dưới đây mô tả nghiệp vụ đích, đối chiếu [contract Rev 1.1 §1–§4 và Phụ lục A](https://callbot-contract-site-rev11.vercel.app/#s1) ngày 18/09/2026. Contract có bảy nhóm tình huống: xác minh danh tính, xác nhận đến khám, hủy, chuyển nhân viên, đổi lịch, không liên lạc được và đặt lịch mới. Inbound chỉ hỗ trợ đặt lịch mới; Outbound xử lý lịch hẹn có sẵn.

Mọi lượt chờ người gọi trả lời đều đi qua kiểm tra ngoại lệ ở mục 3.3, kể cả khi chưa xác minh danh tính. Mọi API đọc/ghi đều áp dụng xử lý lỗi ở mục 4. Các nút “thành công” chỉ được đi tới sau khi Mock xác nhận; không suy ra thành công từ lời người gọi hoặc trạng thái hội thoại.

### 3.1. Inbound — Bệnh nhân gọi vào đặt lịch mới

Đầu vào: `direction=inbound`, `caller_number`, không có `appointment_id`. Số điện thoại chỉ dùng tìm hồ sơ; phải xác minh cả họ tên và ngày sinh trước khi đề xuất lịch. Sơ đồ dùng các endpoint nghiệp vụ dưới tiền tố `/v1`.

```mermaid
flowchart TD
    I_START(["Bệnh nhân gọi vào<br/>direction = inbound"]) --> I_LOOKUP["GET /patients?phone=caller_number"]
    I_LOOKUP --> I_FOUND{"Tìm được đúng một hồ sơ?"}
    I_FOUND -->|Không có hoặc nhiều hồ sơ| I_NOTFOUND["PATIENT_NOT_FOUND<br/>Không tạo hồ sơ bệnh nhân"]
    I_NOTFOUND --> I_TRANSFER
    I_FOUND -->|Có| I_ID["Hỏi mở họ tên và ngày sinh<br/>AWAITING_IDENTITY"]
    I_ID --> I_VERIFY{"Cả hai thông tin khớp hồ sơ?"}
    I_VERIFY -->|Chưa đủ thông tin| I_ASK["Hỏi phần còn thiếu<br/>Áp dụng ngưỡng không hiểu / im lặng"]
    I_ASK --> I_ID
    I_VERIFY -->|Không khớp| I_FAILED["IDENTITY_FAILED<br/>Không tiết lộ chi tiết lịch"]
    I_FAILED --> I_TRANSFER
    I_VERIFY -->|Khớp| I_INTENT{"Nhu cầu sau xác minh<br/>AWAITING_INTENT"}
    I_INTENT -->|Đặt lịch mới| I_NEED["Hỏi cơ sở, khoa và khoảng thời gian mong muốn"]
    I_INTENT -->|Xác nhận, hủy, đổi lịch hoặc việc khác| I_SCOPE["OUT_OF_SCOPE"]
    I_SCOPE --> I_TRANSFER
    I_NEED --> I_SLOTS["GET /slots?clinic_id=&from=&to="]
    I_SLOTS --> I_AVAILABLE{"Có khung giờ phù hợp?"}
    I_AVAILABLE -->|Không| I_ALTERNATIVE{"Người gọi đồng ý tìm khoảng khác?"}
    I_ALTERNATIVE -->|Có| I_NEED
    I_ALTERNATIVE -->|Không, cần nhân viên hỗ trợ| I_SCOPE
    I_AVAILABLE -->|Có| I_OFFER["Chỉ đề xuất giờ API trả về trong cuộc gọi<br/>OFFERING_SLOTS"]
    I_OFFER --> I_CHOICE{"Chọn được một khung giờ hợp lệ?"}
    I_CHOICE -->|Chưa rõ| I_CLARIFY["Làm rõ lựa chọn<br/>Hai lượt không hiểu liên tiếp: mục 3.3"]
    I_CLARIFY --> I_OFFER
    I_CHOICE -->|Muốn khoảng khác| I_NEED
    I_CHOICE -->|Có| I_READBACK["Đọc lại khung giờ đã chọn<br/>Xin xác nhận rõ ràng — AWAITING_CONFIRMATION"]
    I_READBACK --> I_AGREE{"Xác nhận đặt khung giờ này?"}
    I_AGREE -->|Chưa rõ| I_READBACK
    I_AGREE -->|Không / đổi nhu cầu| I_INTENT
    I_AGREE -->|Có| I_BOOK["POST /appointments<br/>patient_id + slot_id + Idempotency-Key"]
    I_BOOK --> I_RESULT{"Kết quả ghi từ Mock?"}
    I_RESULT -->|SLOT_TAKEN| I_SLOTS
    I_RESULT -->|Lỗi khác| I_ERROR["Xử lý lỗi theo mục 4<br/>Đối soát trước khi kết luận"]
    I_ERROR -->|Thử lại cùng thao tác an toàn| I_BOOK
    I_ERROR -->|Không ghi thành công, cần nhân viên| I_SYSTEM["SYSTEM_ERROR"]
    I_SYSTEM --> I_TRANSFER
    I_RESULT -->|Thành công| I_DONE["Đúng một lịch hẹn mới: BOOKED<br/>Thông báo ngày, giờ, cơ sở đã đặt"]
    I_DONE --> I_END(["ended = true<br/>outcome = BOOKED"])

    I_EVENTS["Ngoại lệ tại bất kỳ lượt nào — mục 3.3<br/>Lâm sàng, xin nhân viên, ngoài phạm vi,<br/>hai lượt không hiểu hoặc ba lượt im lặng"] --> I_TRANSFER["Chuyển nhân viên với lý do phù hợp<br/>Không tạo lịch; không ghi vào Mock"]
    I_TRANSFER --> I_TEND(["ended = true<br/>outcome = TRANSFERRED"])
```

Inbound chuyển máy không gọi `/appointments/{id}/transfer` vì chưa có lịch hẹn. Harness kiểm tra `outcome=TRANSFERRED` và nhật ký không có lệnh ghi cho cuộc gọi; không chấm `transfer_reason` của nhánh này (§2.1). Lý do vẫn được giữ trong ngữ cảnh/trace để nhân viên tiếp nhận. Nếu tạo lịch bị timeout và chưa rõ kết quả, phải đối soát theo mục 4 trước khi chọn nhánh kết thúc; không thể coi là “chưa tạo” chỉ vì chưa nhận được phản hồi.

### 3.2. 

Đầu vào: `direction=outbound`, `appointment_id`. Danh sách gọi trong ngày có thể lấy từ `GET /appointments?date=&clinic_id=`; mỗi phiên chỉ được ghi vào lịch hẹn đã chỉ định lúc bắt đầu. HTTP harness cấp trực tiếp mã này, không cần thực sự quay số. Trong sơ đồ, `/appointments/id` viết gọn cho `/appointments/{appointment_id}` của phiên; các endpoint nằm dưới `/v1`.

```mermaid
flowchart TD
    O_START(["Bot gọi ra<br/>direction = outbound + appointment_id"]) --> O_LOAD["GET /appointments/id<br/>Đọc lịch, danh tính đối chiếu và version"]
    O_LOAD --> O_CONTACT{"Kết quả liên lạc?"}
    O_CONTACT -->|Không bắt máy| O_NOANSWER["NO_ANSWER"]
    O_CONTACT -->|Máy bận| O_BUSY["LINE_BUSY"]
    O_CONTACT -->|Hộp thư thoại| O_VM["VOICEMAIL<br/>Không để lại chi tiết lịch hẹn"]
    O_NOANSWER --> O_UNREACHABLE
    O_BUSY --> O_UNREACHABLE
    O_VM --> O_UNREACHABLE
    O_CONTACT -->|Người nghe phản hồi| O_ID["Hỏi mở họ tên và ngày sinh<br/>AWAITING_IDENTITY"]
    O_ID --> O_VERIFY{"Cả hai thông tin khớp hồ sơ?"}
    O_VERIFY -->|Chưa đủ thông tin| O_ASK["Hỏi phần còn thiếu<br/>Áp dụng ngưỡng không hiểu / im lặng"]
    O_ASK --> O_ID
    O_VERIFY -->|Không khớp| O_FAILED["IDENTITY_FAILED<br/>Không tiết lộ chi tiết lịch"]
    O_FAILED --> O_TRANSFER
    O_VERIFY -->|Khớp| O_INTENT{"Nhu cầu của bệnh nhân?<br/>AWAITING_INTENT"}

    O_INTENT -->|Đến khám| O_READ["Đọc lại ngày, giờ và cơ sở<br/>AWAITING_CONFIRMATION"]
    O_READ --> O_AGREE{"Đồng ý nội dung đọc lại?"}
    O_AGREE -->|Có| O_CONFIRM["POST /appointments/id/confirm"]
    O_AGREE -->|Không / thay đổi ý định| O_INTENT
    O_AGREE -->|Chưa rõ| O_READ

    O_INTENT -->|Không đến / muốn hủy| O_CANCELASK["Làm rõ ý định hủy và lý do<br/>Xin xác nhận hủy lần thứ hai"]
    O_CANCELASK --> O_CANCELYES{"Xác nhận hủy lần hai rõ ràng?"}
    O_CANCELYES -->|Có| O_CANCEL["POST /appointments/id/cancel<br/>cancel_reason theo Phụ lục A"]
    O_CANCELYES -->|Không / đổi ý| O_INTENT
    O_CANCELYES -->|Chưa rõ| O_CANCELASK

    O_INTENT -->|Đổi lịch| O_NEED["Hỏi khoảng thời gian mong muốn"]
    O_NEED --> O_SLOTS["GET /slots?clinic_id=&from=&to="]
    O_SLOTS --> O_AVAILABLE{"Có khung giờ phù hợp?"}
    O_AVAILABLE -->|Không| O_ALTERNATIVE{"Đồng ý tìm khoảng khác?"}
    O_ALTERNATIVE -->|Có| O_NEED
    O_ALTERNATIVE -->|Không, cần nhân viên hỗ trợ| O_SCOPE
    O_AVAILABLE -->|Có| O_OFFER["Chỉ đề xuất giờ API trả về trong cuộc gọi<br/>OFFERING_SLOTS"]
    O_OFFER --> O_CHOOSE{"Chọn và đồng ý giờ mới?"}
    O_CHOOSE -->|Chưa rõ| O_OFFER
    O_CHOOSE -->|Muốn khoảng khác| O_NEED
    O_CHOOSE -->|Đổi ý| O_INTENT
    O_CHOOSE -->|Có| O_RESCHEDULE["POST /appointments/id/reschedule<br/>new_slot_id; requested_by = PATIENT<br/>Đặt giờ mới và trả giờ cũ nguyên tử"]
    O_RESCHEDULE -->|SLOT_TAKEN: đọc lại và xin chọn lại| O_SLOTS

    O_CONFIRM --> O_RESULT
    O_CANCEL --> O_RESULT
    O_RESCHEDULE -->|Thành công hoặc lỗi khác| O_RESULT{"Kết quả ghi từ Mock?"}
    O_RESULT -->|Thành công| O_DONE["Thông báo kết quả đã ghi<br/>CONFIRMED / CANCELLED / RESCHEDULED"]
    O_DONE --> O_END(["ended = true<br/>outcome = trạng thái Mock đã xác nhận"])
    O_RESULT -->|Lỗi| O_ERROR["Xử lý lỗi theo mục 4<br/>Đọc lại / đối soát / thử lại an toàn"]
    O_ERROR -->|Khôi phục được| O_RETRY["Trở lại đúng thao tác đang chờ<br/>Kiểm tra dữ liệu và xác nhận còn hiệu lực"]
    O_RETRY -->|SLOT_TAKEN khi đổi lịch| O_SLOTS
    O_RETRY -->|Thành công hoặc lỗi khác| O_RESULT
    O_ERROR -->|Không khôi phục được| O_SYSTEM["SYSTEM_ERROR"]
    O_SYSTEM --> O_TRANSFER

    O_INTENT -->|Ngoài phạm vi| O_SCOPE["OUT_OF_SCOPE"]
    O_SCOPE --> O_TRANSFER
    O_EVENTS["Ngoại lệ tại bất kỳ lượt nào — mục 3.3<br/>Lâm sàng, xin nhân viên, ngoài phạm vi,<br/>hai lượt không hiểu liên tiếp"] --> O_TRANSFER["POST /appointments/id/transfer<br/>transfer_reason phù hợp"]
    O_TRANSFER -->|Mock xác nhận thành công| O_TEND(["ended = true<br/>outcome = TRANSFERRED"])
    O_SILENCE["Ba lượt im lặng liên tiếp<br/>SILENCE — kể cả lúc hỏi danh tính"] --> O_UNREACHABLE["POST /appointments/id/unreachable<br/>Chỉ gửi unreachable_reason<br/>Mock tự tăng attempt_count đúng một lần"]
    O_UNREACHABLE -->|Mock xác nhận thành công| O_UEND(["ended = true<br/>outcome = UNREACHABLE"])
    O_TRANSFER -->|Lỗi ghi| O_TERMINAL_ERROR["Áp dụng mục 4<br/>Không giả định trạng thái đã được ghi"]
    O_UNREACHABLE -->|Lỗi ghi| O_TERMINAL_ERROR
```

Nhánh xác nhận chỉ thành công khi Mock có `CONFIRMED`, `confirmed_at` và `confirmed_via=callbot`. Nhánh hủy phải có `CANCELLED` và `cancel_reason`; “không đến được” chưa đủ để ghi hủy nếu thiếu xác nhận lần hai. Nhánh đổi phải có `RESCHEDULED`, `new_slot_id` và đã giải phóng khung giờ cũ; không tách thành hủy lịch cũ rồi đặt mới (§1.1.3–§1.1.6, §2.2).

`NO_ANSWER` và `LINE_BUSY` là tín hiệu của cuộc gọi điện thoại thực; câu người nghe nói “tôi đang bận” không tự chứng minh máy bận. Trên đường HTTP chấm điểm, harness tạo `VOICEMAIL` bằng clip lời chào và `SILENCE` bằng `silence_ms > 0` (§4.2.5). Việc gọi lại ở lần sau không có lịch hay số lần tối đa được contract quy định; sơ đồ chỉ mô tả một lần liên lạc.

### 3.3. Ngoại lệ được kiểm tra trong suốt hai luồng

```mermaid
flowchart TD
    E_TURN(["Nhận một lượt hoặc tín hiệu cuộc gọi"]) --> E_SILENT{"Lượt im lặng?"}
    E_SILENT -->|Có| E_COUNT{"Đủ ba lượt im lặng liên tiếp?"}
    E_COUNT -->|Chưa| E_PROMPT["Nhắc / hỏi lại tại bước hiện tại<br/>Không tính là một lần không hiểu"]
    E_COUNT -->|Đủ| E_DIR{"Hướng cuộc gọi?"}
    E_DIR -->|Inbound| E_NOTUNDERSTOOD["NOT_UNDERSTOOD"]
    E_DIR -->|Outbound| E_UNREACHABLE["Nhánh UNREACHABLE ở mục 3.2<br/>unreachable_reason = SILENCE"]
    E_SILENT -->|Không| E_CONTENT{"Nội dung / tín hiệu nhận được?"}
    E_CONTENT -->|Hộp thư thoại ở outbound| E_VM["Nhánh UNREACHABLE ở mục 3.2<br/>unreachable_reason = VOICEMAIL"]
    E_CONTENT -->|Hỏi lâm sàng, thuốc, phân loại cấp cứu| E_CLINICAL["CLINICAL_QUESTION<br/>Không đưa ra tư vấn"]
    E_CONTENT -->|Xin nói chuyện với nhân viên| E_REQUEST["PATIENT_REQUEST"]
    E_CONTENT -->|Ngoài các nghiệp vụ được hỗ trợ| E_SCOPE["OUT_OF_SCOPE"]
    E_CONTENT -->|Không hiểu| E_FAILURES{"Hai lượt không hiểu liên tiếp?"}
    E_FAILURES -->|Chưa| E_CLARIFY["Hỏi lại để làm rõ<br/>Không đoán ý định hoặc dữ liệu"]
    E_FAILURES -->|Đủ| E_NOTUNDERSTOOD
    E_CONTENT -->|Hiểu và đúng phạm vi| E_CONTINUE["Tiếp tục bước hiện tại của Inbound / Outbound"]
    E_NOTUNDERSTOOD --> E_TRANSFER["Nhánh chuyển nhân viên của hướng tương ứng<br/>Inbound: không ghi Mock<br/>Outbound: POST /appointments/id/transfer"]
    E_CLINICAL --> E_TRANSFER
    E_REQUEST --> E_TRANSFER
    E_SCOPE --> E_TRANSFER
```

Hai bộ đếm độc lập và chỉ đếm chuỗi liên tiếp của loại tương ứng. Im lặng không được tính vào ngưỡng hai lần không hiểu. Contract không quy định một số lần thử danh tính riêng; khi dữ liệu còn thiếu có thể hỏi tiếp, nhưng danh tính không khớp phải chuyển ngay và mọi lượt vẫn chịu các ngưỡng trên (§1.1.1–§1.1.2, §1.1.5, §1.1.7–§1.1.9).

| Tình huống chuyển nhân viên | `transfer_reason` | Ràng buộc |
|---|---|---|
| Tên hoặc ngày sinh không khớp; người nghe không xác minh được là bệnh nhân | `IDENTITY_FAILED` | Không đọc sẵn tên/ngày sinh để người nghe đồng ý; không tiết lộ chi tiết lịch. |
| Inbound không tìm được duy nhất một hồ sơ | `PATIENT_NOT_FOUND` | Không tạo bệnh nhân mới. |
| Thanh toán, bảo hiểm, chuyển tuyến, quy trình đơn thuốc; hoặc nghiệp vụ không thuộc hướng gọi đang xử lý | `OUT_OF_SCOPE` | Không thực hiện quy trình ngoài phạm vi (§1.2.3). |
| Chẩn đoán, giải thích triệu chứng, tư vấn thuốc, quyết định lâm sàng hoặc phân loại cấp cứu | `CLINICAL_QUESTION` | Chuyển mỗi khi gặp; không tự trả lời (§1.2.1, SF-04). |
| Hai lượt không hiểu liên tiếp; hoặc Inbound im lặng ba lượt liên tiếp | `NOT_UNDERSTOOD` | Không đoán để tiếp tục nghiệp vụ. |
| Người gọi chủ động xin gặp nhân viên | `PATIENT_REQUEST` | Chuyển theo yêu cầu. |
| Lỗi hệ thống không thể khôi phục | `SYSTEM_ERROR` | Xử lý tình trạng ghi chưa rõ trước khi báo kết quả; xem mục 4. |

### 3.4. Đối chiếu độ bao phủ contract

| Nhóm tình huống / điều khoản | Inbound | Outbound |
|---|---|---|
| Khai báo hướng gọi — §1.1.8 | Không có `appointment_id`; tra theo `caller_number`. | Có `appointment_id` chỉ định. |
| Xác minh — §1.1.1–§1.1.2, §1.1.9; SF-03 | Tìm đúng một hồ sơ, hỏi mở tên + ngày sinh, đối chiếu cả hai trước khi đề xuất. | Hỏi mở tên + ngày sinh, đối chiếu cả hai trước khi tiết lộ lịch. |
| Xác nhận đến khám — §1.1.3 | Chuyển ngoài phạm vi. | Đọc lại ngày, giờ, cơ sở; chỉ ghi sau khi bệnh nhân đồng ý. |
| Hủy — §1.1.4; SF-05 | Chuyển ngoài phạm vi. | Xác nhận lần hai rõ ràng; ghi lý do hợp lệ. |
| Chuyển nhân viên — §1.1.5, §1.2.1, §1.2.3; SF-04 | `TRANSFERRED`, không có lệnh ghi Mock. | `/transfer` với lý do hợp lệ. |
| Đổi lịch — §1.1.6; SF-02 | Chuyển ngoài phạm vi. | Chỉ dùng giờ `/slots` trả về trong cuộc gọi; đặt mới và trả cũ nguyên tử. |
| Không liên lạc được — §1.1.7, §4.2.5 | Ba lượt im lặng → chuyển `NOT_UNDERSTOOD`, không tạo lịch. | `NO_ANSWER`, `VOICEMAIL`, `LINE_BUSY`, `SILENCE` → `/unreachable`; không để chi tiết trên voicemail. |
| Đặt mới — §1.1.9–§1.1.10; SF-01–SF-02 | Chọn giờ hợp lệ, xác nhận rõ ràng, tạo đúng một lịch `BOOKED`. | Ngoài phạm vi luồng gọi ra; chuyển nhân viên. |
| Trạng thái kết thúc — §2.1–§2.3 | `BOOKED` hoặc `TRANSFERRED` theo hai nhánh trên. | Trạng thái Mock của đúng lịch đang gọi; các nhánh ở mục 3.2. |
| Lỗi API, ghi an toàn — §4.2.2–§4.2.5, Phụ lục A; SF-01 | Chống tạo trùng; xử lý slot bị chiếm và kết quả chưa rõ. | Chống ghi sai lịch/lặp thao tác; xung đột phiên bản và retry `/unreachable`. |

Các nhánh hết giờ phù hợp, tìm khoảng khác và đối soát timeout là cách xử lý thiết kế để hoàn chỉnh luồng; contract không ấn định số lần tìm lại, retry hay mã lý do riêng cho “hết giờ trống”. Sơ đồ dùng chuyển `OUT_OF_SCOPE` khi yêu cầu không thể hoàn tất trong phạm vi hỗ trợ, hoặc `PATIENT_REQUEST` nếu người gọi xin gặp nhân viên; không tự tạo thêm giá trị enum.

## 4. Ngoại lệ API và nguyên tắc ghi dữ liệu

### 4.1. Điều kiện trước khi ghi và trạng thái kết thúc

Mọi lệnh ghi phải có `Idempotency-Key`; hợp đồng khuyến nghị `If-Match` với phiên bản vừa đọc khi cập nhật bản ghi đã có. Gateway kiểm tra đúng lịch hẹn, đúng khung giờ được `/slots` trả về trong cuộc gọi và đủ xác nhận cho hành động. Clinic Mock là nguồn duy nhất có thẩm quyền về trạng thái lịch hẹn; chỉ giữ bản đọc tạm trong ngữ cảnh. Bot không được gọi `/_harness/*` (§4.2.2–§4.2.4).

| Thao tác | Điều kiện / dữ liệu bắt buộc | Kết quả thành công |
|---|---|---|
| Inbound tạo lịch | Đúng bệnh nhân đã xác minh, `slot_id` hợp lệ, xác nhận rõ ràng khung giờ. | Đúng một bản ghi `BOOKED`. |
| Outbound xác nhận | Danh tính đã xác minh; bệnh nhân đồng ý sau khi đọc lại ngày, giờ, cơ sở. | `CONFIRMED`, có `confirmed_at`, `confirmed_via=callbot`. |
| Outbound hủy | Danh tính đã xác minh; xác nhận hủy lần hai rõ ràng. `cancel_reason`: `PATIENT_UNAVAILABLE`, `NO_LONGER_NEEDED`, `WENT_ELSEWHERE`, `COST`, `UNSPECIFIED`. | `CANCELLED` và lý do. Không suy đoán lý do; dùng `UNSPECIFIED` khi không xác định được. |
| Outbound đổi lịch | Giờ mới hợp lệ và bệnh nhân đồng ý; `new_slot_id`, `requested_by=PATIENT`. | `RESCHEDULED`, `new_slot_id`; khung giờ cũ được giải phóng trong cùng thao tác. |
| Outbound chuyển nhân viên | `transfer_reason` theo mục 3.3. Có thể chuyển trước khi xác minh. | `TRANSFERRED` và lý do. |
| Outbound không liên lạc được | Body chỉ có `unreachable_reason`: `NO_ANSWER`, `VOICEMAIL`, `LINE_BUSY`, `SILENCE`. Không yêu cầu xác minh. | Mock nguyên tử ghi `UNREACHABLE`, lý do, tăng `attempt_count` đúng một và tăng `version`. Bot không gửi `attempt_count`. |
| Inbound chuyển nhân viên | Lý do theo mục 3.3; không gọi API ghi. | Phản hồi cuối `TRANSFERRED`; không tạo lịch, không ghi Mock. |

Khi `ended=true`, `outcome` phải thuộc đúng bảy trạng thái contract: `CONFIRMED`, `CANCELLED`, `RESCHEDULED`, `TRANSFERRED`, `UNREACHABLE`, `BOOKED`, `SCHEDULED`. `SCHEDULED` biểu thị lịch chưa thay đổi, thường bị chấm thất bại trừ khi kịch bản mong đợi; không được dùng để che lỗi ghi. `state` hội thoại là enum riêng: `AWAITING_IDENTITY`, `AWAITING_INTENT`, `AWAITING_CONFIRMATION`, `OFFERING_SLOTS`, `CLOSING`, `ENDED` (§2.2–§2.3, Phụ lục A).

### 4.2. Xử lý toàn bộ mã lỗi trong contract

| Tình huống | Hành vi của luồng |
|---|---|
| `409 SLOT_TAKEN` khi đặt/đổi | Đọc lại `/slots`, đề xuất lại và xin chọn/xác nhận giờ mới. Không retry mù khung giờ cũ, không tự chọn giờ thay thế. |
| `409 VERSION_CONFLICT` | Đọc lại lịch hẹn, kiểm tra trạng thái và thao tác còn phù hợp; thử lại với `If-Match` mới. Với `/unreachable`, contract yêu cầu giữ nguyên `Idempotency-Key` cho cùng lần liên lạc. Nếu dữ liệu ảnh hưởng nội dung đã xác nhận thay đổi, phải làm rõ/xác nhận lại trước khi ghi. |
| Gửi lại `/unreachable` đã thành công | Mock kiểm tra khóa idempotency trước phiên bản; cùng khóa trả lại 200 cũ dù `If-Match` đã cũ, không tăng `attempt_count` lần hai. Sau 409, đọc lại và dùng cùng khóa; không coi 409 là thành công (§4.2.5). |
| `400 INVALID_REQUEST` | Kiểm tra và sửa request; riêng `/unreachable` không gửi `attempt_count`. Nếu không khôi phục được, xử lý `SYSTEM_ERROR`. |
| `401 BAD_KEY` | Lỗi xác thực API, không phải sai danh tính bệnh nhân. Xử lý `SYSTEM_ERROR`; không lặp lại vô hạn với khóa lỗi. |
| `404 NOT_FOUND` | Không ghi sang một lịch khác để thay thế; xử lý `SYSTEM_ERROR` khi tài nguyên cần thiết không tồn tại. Riêng tra cứu Inbound thành công nhưng không có đúng một hồ sơ đi nhánh `PATIENT_NOT_FOUND`. |
| `429 RATE_LIMITED` / `503 UPSTREAM` | Có thể thử lại có giới hạn theo chính sách vận hành; giữ khóa cho cùng thao tác và bảo đảm thời hạn phản hồi HTTP. Không khôi phục được thì xử lý `SYSTEM_ERROR`. Contract không ấn định số lần hay khoảng chờ retry. |
| Timeout / mất phản hồi khi ghi | Kết quả chưa rõ không đồng nghĩa ghi thất bại. Đối soát/thử lại cùng thao tác với cùng khóa; không tạo lịch Inbound thứ hai, không tăng số lần liên lạc lần nữa, không thông báo thành công khi chưa có bằng chứng. |
| Không thể ghi `/transfer` hoặc `/unreachable` | Bàn giao lỗi hệ thống cho nhân viên/vận hành, giữ trace để đối soát; không tuyên bố Mock đã có `TRANSFERRED`/`UNREACHABLE`. Contract không định nghĩa một outcome lỗi riêng hay quy trình dự phòng khi Mock mất hoàn toàn; đây không phải nhánh hoàn tất nghiệp vụ thành công. |

Giữ nguyên khóa khi thử lại cùng một thao tác; nếu người gọi chọn khung giờ khác hoặc xác nhận một hành động mới thì đó là thao tác mới, không dùng lại khóa với payload khác. Cách phục hồi các lỗi ngoài ví dụ `SLOT_TAKEN` và `/unreachable` là chính sách thiết kế; danh sách mã lỗi lấy từ [Phụ lục A](https://callbot-contract-site-rev11.vercel.app/#sa).

### 4.3. Các ràng buộc xuyên suốt và kiểm tra kết quả

Năm lỗi nghiêm trọng phải được chặn ở cả hai hướng: ghi sai lịch (SF-01), đề xuất giờ không do `/slots` trả về trong cuộc gọi (SF-02), tiết lộ lịch trước xác minh (SF-03), tư vấn lâm sàng/thuốc/phân loại cấp cứu (SF-04), hủy khi chưa có xác nhận lần hai (SF-05). Harness kiểm tra trạng thái cuối của Mock cùng nhật ký ghi và phản hồi từng lượt; với Inbound chuyển máy, kiểm tra `outcome` và không có lệnh ghi (§2.1, §3).

Chỉ dùng dữ liệu tổng hợp do chương trình cung cấp, kể cả kiểm thử cục bộ. Cuộc gọi demo thực chỉ tới nhân viên chương trình hoặc đồng đội đã đồng ý nhận cuộc gọi; không gọi bệnh nhân thật hoặc số điện thoại trong dữ liệu tổng hợp (§1.2.2, §1.3.3). Hai transport phải dùng cùng lõi nghiệp vụ ở mục 1; đường HTTP chấm điểm và yêu cầu audio/thời hạn phản hồi vẫn áp dụng như mục 2 (§1.3, §4.1).

## 5. Hiện trạng triển khai

Đối chiếu mã nguồn ngày 16/09/2026; đây không phải xác nhận hệ thống đã chạy end-to-end.

| Thành phần | Hiện trạng |
|---|---|
| [HTTP router](../../src/callbot/transports/http/calls.py) | Hai endpoint gọi `CallOrchestrator` thật (F-02, [evidence](../evidence/f02-http-engine.md)); chỉ text mode, `mode=audio` trả 501. Mã lỗi thứ tự lượt / đối soát: [http-api.md](http-api.md). |
| [Session Manager](../../src/callbot/engine/session/manager.py) | Redis tạm thời, TTL, khóa theo `call_id`, replay, nhật ký lệnh Clinic và xóa nội dung sau khi ghi Clinic (F-03, [evidence](../evidence/f03-session-store.md), [vận hành](session-operations.md)). |
| [Call Orchestrator](../../src/callbot/engine/orchestrator.py) | Điều phối lượt với `extraction.InformationExtractor`; `engine/nlu` đã xoá (F-04, [evidence](../evidence/f04-information-extraction-http.md)). |
| [Information Extraction](../../src/callbot/engine/extraction/extractor.py) | Nối vào Orchestrator; IE chỉ nhận `TurnContext` (không hồ sơ bệnh nhân). NER tên few-shot gọi [LLM gateway](llm-gateway.md), chọn OpenAI/Gemini/Groq/OpenRouter, tắt mặc định ([hướng dẫn](name-ner.md)); fallback intent/agreement chưa có adapter. |
| [Dialogue Manager](../../src/callbot/engine/dialogue/manager.py) | Điều phối theo `question_id`, `agreement`, `slot_choice`; bằng chứng xác nhận; `SLOT_TAKEN` đề xuất lại. Bước danh tính (T-02, [evidence](../evidence/t02-identity-dialogue.md)): lượt 0 rẽ nhánh theo tra cứu hồ sơ, nhận tên + ngày sinh gộp / ngày sinh trước, câu hỏi lại riêng cho ngày sinh không hợp lệ. Chưa dùng LLM. |
| [Identity Verifier](../../src/callbot/engine/verification/identity.py) | T-01 ([evidence](../evidence/t01-identity-verifier.md)): hai pha theo luồng PDF — `prepare()` ở lượt 0 chuẩn hóa số gọi đến, đọc hồ sơ qua Gateway (lần duy nhất), giữ `{patient_id, full_name, dob}` trong `CallContext.identity_reference`; `verify()` đối chiếu không I/O, inbound đòi đúng một hồ sơ khớp cả hai. Nhánh "không có ứng viên → không hỏi tên" chờ T-02 nối `PrepareResult.transfer_reason` vào `opening()`. |
| [Policy](../../src/callbot/engine/policy/policy_engine.py) | Bộ đếm theo thiết kế IE §6.1; im lặng: outbound `UNREACHABLE`, inbound chuyển máy. Danh tính dùng chung ngưỡng §1.1.5 (IE §6.2); không nhớ / không cung cấp hai lần → `IDENTITY_FAILED`; tra cứu lượt 0 thất bại → chuyển máy ở lượt 1. |
| [Clinic Gateway](../../src/callbot/engine/tools/clinic_gateway.py) | Kiểm tra FSM + guardrail + bằng chứng trước mọi lệnh ghi; có `/unreachable`, hủy gửi `confirmed=true`. F-05 ([evidence](../evidence/f05-clinic-gateway.md)): đọc hết trang, chuẩn hóa slot/patient/appointment, lỗi ba lớp không lộ `httpx`, `FakeClinicAPI` hành xử như mock, contract test fake ↔ mock thật. |
| [Speech pipeline](../../src/callbot/speech/pipeline.py) | Có STT pipeline; xử lý streaming và ngắt lời còn TODO. |
| [TTS](../../src/inference/tts/base.py) | Có interface và `NullTTS`, chưa sinh tiếng nói thật. |
| Phone Adapter | Chưa có transport điện thoại trong repo. |
| Output Guard | Là phần của thiết kế đích; chưa có một bước kiểm tra đầu ra tập trung trong Orchestrator. |

## 6. Tài liệu đối chiếu

- [Hợp đồng — phạm vi và hai kênh dùng chung lõi](https://callbot-contract-site-rev11.vercel.app/#s1).
- [Hợp đồng — trạng thái kết thúc và cách chấm Inbound chuyển máy](https://callbot-contract-site-rev11.vercel.app/#s2).
- [Hợp đồng — năm lỗi nghiêm trọng SF-01–SF-05](https://callbot-contract-site-rev11.vercel.app/#s3).
- [Hợp đồng — API, trạng thái và thao tác unreachable](https://callbot-contract-site-rev11.vercel.app/#s4).
- [Hợp đồng — enum và mã lỗi](https://callbot-contract-site-rev11.vercel.app/#sa).
- [Hợp đồng — thay đổi Rev 1.1](https://callbot-contract-site-rev11.vercel.app/#sc).
- [Thiết kế Information Extraction](information-extraction-design.md).
- [Tài liệu Clinic Mock](clinic-mock.md).
