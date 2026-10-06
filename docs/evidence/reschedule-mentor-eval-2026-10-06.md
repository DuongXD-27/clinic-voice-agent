# Evidence: Sửa luồng đổi lịch theo eval mentor (qc-rs-02 đến qc-rs-08)

## 1. Mục tiêu và phạm vi

Platform eval của mentor gọi vào callbot và clinic mock của nhóm, người gọi theo kịch bản của mentor. Lần chạy
ngày 05/10/2026 có **7 case đổi lịch fail**, cả 7 đều kết thúc với lịch hẹn vẫn ở `SCHEDULED`.

Mục tiêu:

1. **Cả 7 case pass**, và pass ổn định:
   - không phụ thuộc tầng LLM: model trả đúng, không có model hay model timeout đều phải ra cùng kết quả;
   - không phụ thuộc dữ liệu seed: harness seed dữ liệu riêng cho từng case (contract §4.3).
2. **Sửa theo nguyên nhân gốc, không sửa theo câu chữ của kịch bản.** Mỗi cách sửa phải đúng với các cách nói khác
   cùng ý, đo bằng một bộ câu held-out không lấy từ test hay eval nào.
3. **Không nới an toàn:**
   - 0 lệnh ghi sai (unsafe / wrong-slot write);
   - hủy vẫn cần hai lượt xác nhận (SF-05);
   - không lộ lịch trước khi xác minh (SF-03);
   - chỉ đề xuất khung do GET /slots trả về (SF-02);
   - không đoán khi chưa rõ (§1.1.5).

**Chuẩn đối chiếu.** Contract (`tailieu/callbot-contract-vi.md`) là chuẩn. PRD v2.1 dùng để tham khảo: R-23,
R-29, R-43, R-44, GC-RES-03/04/08/09.

**Ngoài phạm vi.**

- Không sửa prompt hay cách gọi tầng LLM. Mọi thay đổi nằm ở luật IE, Dialogue Manager, FSM và guardrail.
- Chỉ sửa luồng đổi lịch. Luồng xác nhận đi khám, hủy lịch, định danh và đặt lịch inbound giữ nguyên hành vi.

## 2. Failure cases ban đầu

### 2.1 Tóm tắt

| Case | Kịch bản | Kỳ vọng | Thực tế | Hỏng ở lượt | Hỏng ở tầng |
| --- | --- | --- | --- | --- | --- |
| qc-rs-02-trap-phantom-slot | Xin 5 giờ chiều 14/10 (không có khung), nhận 3 giờ | RESCHEDULED | SCHEDULED | 4, 5 | IE (intent, veto), Dialogue |
| qc-rs-03-relative-date | "Sáng mai khoảng 9 giờ có được không?", rồi nhận 3 giờ 14/10 | RESCHEDULED | SCHEDULED | 4 | Dialogue |
| qc-rs-04-colloquial-time | "ba giờ kém mười lăm chiều ngày 14" (14:45, không có khung), nhận 3 giờ | RESCHEDULED | SCHEDULED | 5 | Dialogue |
| qc-rs-05-numeric-time | "Đổi sang 15h ngày 14/10", "Đúng rồi, 15 giờ" | RESCHEDULED | SCHEDULED | 5 | IE (agreement) |
| qc-rs-06-mid-flow-correction | "ngày 15… à không, vẫn ngày 14 nhưng sớm hơn chút" | RESCHEDULED | SCHEDULED | 4, 5 | IE (parser), Dialogue |
| qc-rs-07-data-overload | Họ tên, ngày sinh và yêu cầu đổi lịch nói trong một câu | RESCHEDULED | SCHEDULED | 1, 2 | IE, Session, Dialogue |
| qc-rs-08-refuse-all-slots | Từ chối mọi khung, "Không có 5 giờ thì thôi" | TRANSFERRED · PATIENT_REQUEST | SCHEDULED | 6 | IE, Dialogue |

Dữ liệu mock của eval:

- apt_00417 lúc 15:30 thứ Tư 14/10/2026 (`slot_77aa`);
- ngày 14/10 chỉ còn một khung trống: `slot_91d2` lúc 15:00;
- các ngày sau: 15/10 10:30 và 15:30, 16/10 9:00 và 14:00, …;
- đồng hồ lúc chạy eval: 05/10/2026 15:16 (+07:00).

### 2.2 Chi tiết từng case

**qc-rs-02-trap-phantom-slot.** Bẫy của case: không được ghi khung 5 giờ "ma".

- **Lượt 4 "Đổi cho tôi sang 5 giờ chiều ngày 14":** khi chỉ chạy luật, câu không khớp từ khóa "đổi sang", vì có
  "cho tôi" chen giữa. Bot trả "em chưa hiểu". Trên eval, lượt này qua được nhờ LLM (model trả CHANGE_INTENT, mất 1,75 s).
- **Lượt 5 "Không có thì 3 giờ cũng được":** bot không ghi mà đọc lại câu chốt "Em xin xác nhận lại việc đổi lịch
  sang 3 giờ…, đồng ý chứ ạ?", rồi hết kịch bản. Có hai nguyên nhân chồng nhau:
  - Chọn khung luôn phải đi qua một câu chốt "đồng ý chứ ạ?".
  - Chữ "không" trong vế điều kiện "không có thì" bị veto R-41 coi là phủ định. Nên dù bỏ câu chốt, guardrail
    vẫn chặn lệnh ghi.

**qc-rs-03-relative-date.**

- **Lượt 4 "Sáng mai khoảng 9 giờ có được không?":** đây là câu trả lời cho câu hỏi "có đến khám được không".
  IE ra intent NONE và agreement UNCLEAR (vì chữ "được"), nên bot đọc lại lịch cũ, không gọi GET /slots.
  LLM cũng không cứu được: prompt chỉ cho CHANGE_INTENT khi khách nói rõ "đổi".
- Contract Bảng 1 định nghĩa đổi lịch là "bệnh nhân **yêu cầu một thời điểm khác**", không bắt khách phải nói chữ "đổi".

**qc-rs-04-colloquial-time.**

- **Lượt 4:** đúng nhờ LLM. Parser hiểu "ba giờ kém mười lăm chiều" là 14:45, và bot báo "em chưa thấy khung giờ
  đó" chứ không làm tròn lặng lẽ.
- **Lượt 5 "Thế ba giờ cũng được":** bot đọc câu chốt hỏi xác nhận, hết kịch bản. Cùng nguyên nhân câu chốt với rs-02.

**qc-rs-05-numeric-time.**

- **Lượt 4:** đúng. Bot nói "chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều. Anh chị đổi sang giờ đó nhé ạ?"
- **Lượt 5 "Đúng rồi, 15 giờ":** bot hỏi lại "Dạ, em xác nhận đổi lịch… đồng ý chứ ạ?" Lý do: ở câu chốt khung, IE
  chỉ cho AGREE khi cả câu "giải thích hết" được bằng từ đồng ý và tiểu từ. Phần "15 giờ" còn thừa nên ra
  UNCLEAR, dù riêng "Đúng rồi" ra AGREE. Theo cách hiểu thông thường (và PRD R-23), nhắc lại đúng giờ của khung
  là khẳng định rõ.

**qc-rs-06-mid-flow-correction.**

- **Lượt 4 "Đổi sang ngày 15... à không, vẫn ngày 14 nhưng sớm hơn chút":**
  - Parser lấy ngày đầu tiên (15), không biết "à không" là lời tự sửa, nên bot đọc 2 khung ngày 15/10.
  - "Sớm hơn" bị bỏ qua: không có tiêu chí nào so với giờ lịch hiện tại.
- **Lượt 5 "Ừ, 3 giờ được":** "3 giờ" không khớp khung nào vừa đọc, nên bị coi là yêu cầu mới (tốn vòng 2).
  Kể cả khi đọc đúng khung, câu này vẫn ra UNCLEAR như rs-05.

**qc-rs-07-data-overload.**

- **Lượt 1 "Alo, tôi là Nguyễn Văn A, sinh 14/3/78, tôi muốn đổi lịch sang sớm hơn trong chiều ngày 14":**
  bot xác minh đúng ngay, nhưng sau đó đọc lại lịch và hỏi "có đến khám được không", bỏ mất yêu cầu đổi lịch.
  - Ở câu hỏi danh tính, IE chỉ cho một nhóm intent an toàn, nên RESCHEDULE bị bỏ.
  - Sau khi xác minh, Dialogue luôn đi tới câu đọc lại lịch.
  - Nếu parse cả câu, ngày sinh "14/3/78" sẽ lẫn vào tiêu chí ngày.
- **Lượt 2 "Vâng, 3 giờ được":** bot lại đọc lại lịch.

**qc-rs-08-refuse-all-slots.**

- **Lượt 5 "Không, tôi chỉ đi được 5 giờ chiều thôi":** vòng 1. Bot báo không có khung 5 giờ và đọc các khung trống gần nhất.
- **Lượt 6 "Không có 5 giờ thì thôi":** giờ "5 giờ" trong câu được xét trước lời bỏ "thì thôi", nên bot hiểu là
  khách xin lại 5 giờ và đọc lại khung. Lịch vẫn SCHEDULED.
  - Không thể chỉ đảo thứ tự xét, vì bộ nhận diện bỏ đổi lịch cũ khớp chữ "thôi" đứng riêng. Nó trả True cả
    cho "tôi chỉ đi được 5 giờ chiều thôi" và "thôi lấy khung 2".
  - Kể cả khi nhận ra lời bỏ, chính sách cũ (T-10 D-5d) ở vòng 1 giữ lịch rồi hỏi tiếp "có đến khám không".
    Cuộc gọi không kết thúc, lịch vẫn SCHEDULED. Contract §2.2 chấm SCHEDULED là fail.

## 3. Phương pháp

### 3.1 Tái hiện

- **Chạy đúng lời người gọi của từng case** qua Orchestrator thật trên `FakeClinicAPI.mentor_mock()`. Sim này
  khớp dữ liệu mock đang deploy (đã đối chiếu với `clinic-mock/src/clinic_mock/store.py`). Đồng hồ đặt đúng lúc
  chạy eval.
- **Mỗi case chạy ở 3 chế độ của tầng ngữ nghĩa**, vì log eval cho thấy LLM được gọi ở một số lượt (1,75–1,93 s)
  và có lần model chậm khoảng 6 s:
  - `rule`: không có model.
  - `llm`: model đọc câu nêu giờ khác thành CHANGE_INTENT/RESCHEDULE, như log eval.
  - `timeout`: model lỗi ở mọi lượt được gọi.
- Bản tái hiện khớp eval gần như nguyên văn ở cả 7 case.

### 3.2 Gom nguyên nhân gốc

Không sửa rời từng case. Các case được gom theo nguyên nhân gốc, mỗi nguyên nhân sửa một lần ở đúng tầng:

| # | Nguyên nhân gốc | Tầng | Case bị ảnh hưởng |
| --- | --- | --- | --- |
| RC-1 | Đổi lịch: khách đã chọn rõ khung vừa đọc mà bot vẫn đòi thêm câu "đồng ý chứ ạ?" | Dialogue, FSM, guardrail | rs-02, rs-03, rs-04 |
| RC-2 | "không" trong vế điều kiện ("không có thì…") bị coi là phủ định | IE (veto), guardrail | rs-02 |
| RC-3 | Đồng ý kèm nhắc lại giờ của khung ra UNCLEAR | IE (agreement) | rs-05, rs-06, rs-07 |
| RC-4 | Nêu thời điểm khác ở câu hỏi đến khám, không có chữ "đổi", không được hiểu là đổi lịch; "đổi cho tôi sang" không khớp từ khóa | Dialogue, IE (intent) | rs-03 (rs-02, rs-04 khi không có model) |
| RC-5 | Model lỗi hoặc timeout ở câu đọc lịch thì mọi câu thành "hỏi lại xác nhận", kể cả khi luật đã đọc được giờ khách muốn | Dialogue | rs-02, rs-03, rs-04 khi model chậm |
| RC-6 | Không hiểu lời tự sửa trong câu ("ngày 15… à không, 14") | IE (parser) | rs-06 |
| RC-7 | Không hiểu "sớm hơn / muộn hơn" so với lịch đang đổi | IE (parser), Dialogue | rs-06, rs-07 |
| RC-8 | Yêu cầu nói cùng lượt xác minh danh tính bị bỏ | IE, Session, Dialogue | rs-07 |
| RC-9 | Lời bỏ đổi lịch có nhắc giờ không được nhận ra; chính sách giữ lịch ở vòng 1 không kết thúc cuộc gọi | IE, Dialogue | rs-08 |

### 3.3 Nguyên tắc thiết kế khi sửa

1. **Danh sách cho phép, không phải danh sách loại trừ** (§1.1.5 "không được đoán"):
   - Chỉ ghi khi câu chọn khung chỉ gồm lời đồng ý, giờ / thứ tự khung và các từ nối đã biết.
   - Chỉ coi là xin đổi lịch khi câu có lời xin.
   - Câu nằm ngoài các mẫu đó thì hỏi lại, không đoán.
2. **Không phụ thuộc model.** Mọi quyết định của 7 case đều đọc được bằng luật. Model chỉ có thể làm rõ thêm,
   không được là điều kiện để pass.
3. **Không dựa vào dữ liệu seed.** Ví dụ "sớm hơn" phải lọc theo giờ lịch đang đổi, không được trông vào chuyện
   ngày 14/10 chỉ còn một khung.
4. **IE không thấy hồ sơ hay lịch hẹn** (nguyên tắc 2 của thiết kế IE). Những gì cần giờ lịch hẹn (mốc của
   "sớm hơn", so giờ khác lịch hiện tại) đều làm ở Dialogue, đọc lại lịch từ mock (§4.2.2).
5. **An toàn ghi không đổi.** Guardrail vẫn kiểm lại bằng chứng xác nhận trước mọi lệnh ghi. Veto R-41 vẫn chạy
   trên nguyên câu. Hủy vẫn cần hai lượt.

### 3.4 Kiểm chống overfit

Ngoài test theo case, cách sửa được đo trên khoảng 50 câu held-out, viết mới, không lấy từ test hay eval nào. Kỳ
vọng của các câu này suy ra từ contract, không suy từ code. Các nhóm câu:

- xin giờ khác có lời xin, và có lời xin nhưng nói kiểu khác;
- nêu giờ mà không có lời xin;
- thắc mắc giờ ("9 giờ hả em?") — không được hiểu là đổi lịch;
- các cách nhận khung, và các câu do dự — không được ghi;
- vế điều kiện nói kiểu khác;
- các cách bỏ đổi lịch;
- tự sửa;
- "sớm hơn / muộn hơn" khi seed thêm khung 16:00 ngày 14;
- model timeout.

Mỗi cách sửa phải đúng ở cả nhóm câu nó nhắm tới lẫn nhóm câu không được ghi.

## 4. Hướng giải quyết theo từng nguyên nhân

### RC-1. Chọn rõ một khung vừa đọc thì ghi đổi lịch ngay

- **Căn cứ:**
  - Contract §1.1.6 và ví dụ Reschedule: bot mời một khung, khách "Được, đổi giúp tôi." thì bot ghi luôn. Contract
    chỉ bắt xác nhận lần hai cho hủy (§1.1.4) và xác nhận khung cho đặt lịch (§1.1.10).
  - PRD R-29 / R-23: chọn rõ một giờ bot vừa mời là khẳng định rõ.
- **Cách làm:**
  - `DialogueManager._slot_choice`: khi câu khớp một khung vừa đọc (`_picked`) và `_direct_pick` đúng, bot
    chọn khung, ghi bằng chứng CONFIRMATION (AGREE, nguồn là `slot_choice`) rồi ghi qua `_write_slot`.
    `_write_slot` là phần ghi chung với câu chốt, gồm cả nhánh SlotTaken: đọc lại /slots và đề xuất lại (GC-RES-06).
  - `_direct_pick` đòi đủ năm điều kiện:
    1. việc đang chờ là RESCHEDULE;
    2. câu khớp đúng một khung đã đọc;
    3. câu trả lời đúng câu hỏi ở lượt ngay trước;
    4. không phải câu hỏi lại (`asks_back`);
    5. `explicit_slot_pick` đúng.
  - `explicit_slot_pick` (`extraction/agreement.py`) dùng **danh sách cho phép**:
    - bỏ các cụm thời gian và thứ tự khung (`_strip_slot_time`);
    - bỏ lời đồng ý, đáp lễ, tiểu từ, xưng hô và bổ ngữ chọn khung (`_SLOT_COMPLEMENTS`: "khung đó", "giờ đó",
      "đổi", "lấy", "chọn", "cũng", "thì", …);
    - còn từ nội dung nào khác thì không phải chọn rõ.
    - "dạ" một mình, câu có "?" và câu có veto R-41 không bao giờ là chọn rõ.
  - Câu "3 giờ chiều" khớp 2 khung (một trên trang vừa đọc, một chưa đọc): chọn khung trên trang khi chỉ có đúng
    một khung khớp trên trang. Người gọi đang trả lời trang vừa nghe.
  - `session/fsm.py`: `DIRECT_PICK_QUESTION_FOR = {"RESCHEDULE": OFFER_SLOTS}`. `confirmation_questions(action)`
    trả về tập câu hỏi mở khóa ghi; RESCHEDULE được ghi từ trạng thái OFFERING_SLOTS.
  - `policy/guardrails.py` `assert_action_confirmed`: với câu mời khung, khung được ghi phải nằm trong các khung
    vừa đọc (`_question_covers_slot`). Bằng chứng phải trả lời đúng câu hỏi của lượt ngay trước, như cũ.
- **Giữ nguyên câu đọc lại cho:**
  - đặt lịch (§1.1.10);
  - "khung nào cũng được" (bot tự chọn, khách chưa chọn);
  - câu chọn còn do dự hoặc hỏi lại.

### RC-2. Vế điều kiện "không có / không còn / hết … thì" không phải phủ định

- **Cách làm:**
  - `_FALLBACK_LEAD` nhận vế điều kiện ở đầu câu: "(nếu / vậy / thế) không có | không còn | chẳng có | hết | kín
    … (rồi) thì". `without_fallback_lead` bỏ vế này trước khi tìm khung (extractor) và trước khi xét veto
    (`explicit_slot_pick` và guardrail).
  - Phần còn lại giữ nguyên dấu câu, để "15:30", "14/10" không bị tách thành hai số. Câu không có vế điều kiện
    thì giữ nguyên.
- **An toàn:** guardrail chỉ bỏ vế này cho đổi / đặt lịch, **không bao giờ cho hủy** (SF-05). "Không, 3 giờ" và
  "khung 1… à không, khung 2" vẫn bị veto.

### RC-3. Đồng ý kèm nhắc lại giờ của khung là đồng ý

- **Cách làm:** ở SLOT_READBACK, `_leaves_content` bỏ cụm thời gian (`_strip_slot_time`) trước khi xét phần
  còn lại. Nhờ vậy "Đúng rồi, 15 giờ", "Vâng, ba giờ được" ra AGREE. Khung nhắc tới có đúng là khung đang chốt
  hay không do Dialogue đối chiếu.
- **Nhắc giờ của khung khác** ("Đúng rồi, 10 rưỡi" khi bot đang chốt 3 giờ): không ghi; bot đọc câu chốt của khung 10 rưỡi.
- **Không đổi:** "dạ, 15 giờ" vẫn không phải đồng ý (R-23); câu có phủ định vẫn bị veto.

### RC-4. Nêu thời điểm khác ở câu đọc lịch là yêu cầu đổi lịch

- **Căn cứ:** contract Bảng 1, đổi lịch là "bệnh nhân yêu cầu một thời điểm khác".
- **Cách làm (`DialogueManager._proposes_other_time`)**, ở câu hỏi "có đến khám được không": câu được coi là
  yêu cầu đổi lịch khi đủ các điều kiện sau. Khi đó bot vào luồng đổi lịch với chính câu đó làm tiêu chí.
  1. IE không ra ý định nào và không ra đồng ý / từ chối rõ.
  2. Câu không báo bận.
  3. Câu có **lời xin** (`requests_time`, danh sách cho phép):
     - "được không", "cho tôi", "lấy", "muốn", "rảnh", "đi được", …;
     - câu hỏi còn chỗ "có / còn … không";
     - câu cầu khiến kết bằng "đi" ("5 giờ chiều ngày 14 đi em"), trừ khi ngay trước "đi" là chủ ngữ hay
       trạng từ ("tôi đi", "vẫn đi").
     - Câu có dấu hiệu **thắc mắc** ("tưởng", "không phải", "hả", "à", "sao lại", "nhầm") thì không bao giờ là lời xin.
  4. Tiêu chí thời gian **không khớp lịch hiện tại**, so trước khi quy đổi thứ theo R-30. Nhờ vậy "8 giờ sáng thứ
     Năm" khi lịch đúng là thứ Năm là nhắc lại lịch, không phải thứ Năm tuần này.
- **IE (`extraction/intent.py`):** từ khóa đổi lịch được tổng quát thành mẫu "động từ dời (đổi / dời / chuyển /
  lùi / hoãn) + (lịch) + (giúp / cho / hộ) + xưng hô + sang / qua". Mẫu này nhận "đổi cho tôi sang", "chuyển giúp
  chị qua", "dời lịch hộ em sang", thay cho danh sách câu cố định.
- **Kết quả:** "Sáng mai khoảng 9 giờ có được không?" vào luồng đổi lịch. "9 giờ hả em?", "Ơ, không phải 9 giờ
  à?", "Tôi nhớ là 4 giờ cơ mà" vẫn đọc lại lịch hoặc hỏi lại, không đoán.

### RC-5. Model lỗi hoặc timeout không làm mất yêu cầu đổi lịch

- **Vấn đề:** trước đây model lỗi ở câu đọc lịch luôn dẫn tới hỏi lại xác nhận, kể cả khi luật thời gian đã đọc
  được giờ khách muốn. Một lần chạy bench, rs-03 và rs-04 bị chậm khoảng 6 s rồi hỏi lại.
- **Cách làm (`DialogueManager._time_proposal_without_model`):**
  - Ở CONFIRM_READBACK, model lỗi mà câu thỏa RC-4 (nhận bằng luật trên nguyên câu) thì bot vẫn đi tìm khung.
  - Lệnh ghi của lượt đó vẫn bị chặn (`business_write_blocked`); lượt này chỉ đọc.
  - Câu không nêu giờ mới vẫn hỏi lại như cũ.

### RC-6. Lời tự sửa trong câu: lấy giá trị nói sau cùng

- **Cách làm (`slot_choice._corrected_criteria`):**
  - Nhận các cụm tự sửa ("à không", "à nhầm", "ý tôi là", "mà thôi", "thôi để", …), cùng "à / ờ" trần đứng giữa
    hai giá trị.
  - Lấy tiêu chí của phần nói sau cùng, giữ lại những tiêu chí phần trước có mà phần sau không nhắc lại.
  - Số trần ở phần sửa mượn đơn vị của số bị sửa: "ngày 15… à không, 14" thành ngày 14; "9 giờ, à 10" thành 10 giờ.
- **Đọc đồng ý:** có / không chỉ đọc trên phần nói sau cùng (`without_corrected_part`). Veto R-41 vẫn chạy trên
  nguyên câu, nên lời đồng ý lẫn phủ định vẫn bị hạ xuống UNCLEAR.
- Chỉ áp dụng cho tiêu chí giờ / ngày của việc đổi lịch. Họ tên và ngày sinh ở bước định danh không đổi.

### RC-7. "Sớm hơn / muộn hơn" so với lịch đang đổi

- **Vấn đề:** "sớm hơn" chỉ được coi là "xin khung khác", không có mốc. Với dữ liệu eval, rs-06 và rs-07 chỉ
  đúng vì ngày 14/10 còn đúng một khung. Seed thêm một khung 16:00 thì bot đọc cả khung muộn hơn lịch cũ.
- **Cách làm:**
  - **IE:** `SlotCriteria` có thêm `relative` (EARLIER / LATER), `before`, `after` (`extraction/schema.py`).
    Parser nhận "sớm hơn (chút / một chút)", "muộn hơn", "trễ hơn" (`_RELATIVE`, `_take_relative`). IE không biết
    giờ lịch hẹn, nên tiêu chí tương đối **chưa có mốc thì không khớp khung nào** (`_matches`): đó là yêu cầu mới,
    không phải chọn khung.
  - **Dialogue:** `_request_criteria` đọc `starts_at` của lịch đang đổi từ mock rồi gắn mốc (`anchor_relative`:
    EARLIER thành `before`, LATER thành `after`). Dùng ở `_offer_slots` và `_unoffered`. `_dates_only` (kiểm
    ngày xin còn khung không) bỏ phần sớm / muộn.
  - "Sớm hơn" trần ở câu chọn khung vẫn là xin khung khác (T-10 R033): sớm hơn khung vừa đọc hay lịch cũ là mơ hồ.
- **Kết quả:** "vẫn ngày 14 nhưng sớm hơn chút" chỉ đọc khung ngày 14 bắt đầu trước 15:30. "Đổi sớm hơn được
  không em", "Muộn hơn chút được không" ở câu đọc lịch vào luồng đổi lịch với đúng chiều so sánh.

### RC-8. Yêu cầu đổi lịch nói trước khi xác minh xong được giữ lại

- **Căn cứ:** contract §1.1.1 và SF-03 (không lộ gì trước khi xác minh); PRD R-43.
- **Cách làm:**
  - **IE (`_early_intent`):** ở câu hỏi danh tính của cuộc gọi đi, nếu lượt đã cho họ tên hoặc ngày sinh, IE tìm
    thêm ý định **đổi lịch** nằm **ngoài vùng tên**. `_without_identity` bỏ vùng họ tên và ngày sinh khỏi lời yêu
    cầu (`ExtractionResult.early_request`), nên ngày sinh "14/3/78" không thành ngày muốn đổi.
  - **Dialogue (`_note_early_intent`):** lưu ý định và lời yêu cầu vào phiên (`CallContext.early_intent`,
    `early_request`). Chưa làm gì, chưa nói gì.
  - **Xác minh xong (`_early_flow`):** bot đi thẳng vào luồng đổi lịch, tra khung theo lời yêu cầu đã lưu, không
    hỏi lại "có đến khám được không".
  - Xác minh sai thì chuyển máy như cũ; yêu cầu đã lưu bị bỏ, không đọc khung, không ghi.
- **Không mang qua yêu cầu hủy:** hủy cần hai lượt xác nhận (SF-05), nên lời hủy nói cùng lượt xác minh vẫn đi
  như cũ (đọc lịch, khách nói lại ý định).

### RC-9. Bỏ đổi lịch: giữ lịch cũ và chuyển nhân viên

- **Căn cứ:**
  - Contract không quy định trường hợp khách bỏ giữa luồng đổi lịch.
  - Kỳ vọng của mentor ở rs-08 là TRANSFERRED · PATIENT_REQUEST, và contract §2.2 chấm SCHEDULED là fail.
  - PRD GC-RES-09 cùng hướng.
- **Cách làm:**
  - **Nhận diện (`gives_up_if_unavailable`, `_DROP_CHANGE`):** chỉ các cụm bỏ rõ — "thì thôi", "thôi khỏi",
    "thôi bỏ đi", "thì bỏ qua", "thôi vậy", "giữ lịch cũ", "để nguyên", "không đổi nữa", …. Không tính "thôi"
    đứng riêng, nên "tôi chỉ đi được 5 giờ chiều thôi" và "thôi lấy khung 2" không bị hiểu là bỏ.
  - **Thứ tự xét (`_slot_choice`):** lời bỏ được xét **trước** giờ trong câu, vì ở "Không có 5 giờ thì thôi" giờ
    là điều kiện vừa không có, không phải yêu cầu mới. Ngoại lệ: câu vẫn nhận một khung vừa đọc ("thôi khỏi, 3
    giờ cũng được") thì là chọn khung.
  - **Hành động (`_give_up` → `_rounds_exhausted`):** đang đổi lịch thì ở mọi vòng đều giữ nguyên lịch cũ, không
    ghi gì, chuyển nhân viên PATIENT_REQUEST. Đặt lịch inbound bỏ ngang thì chưa có lịch nào để giữ, nên bot hỏi lại nhu cầu.

### Sửa kèm: câu chỉ nêu ngày dạng số

- **Vấn đề:** ở câu chọn khung, "20/10" ra "chưa hiểu" và "đổi sang 19/10 buổi sáng" mất ngày (eval R139, R140).
  Bước bỏ vế điều kiện trả về câu đã bỏ dấu câu, nên "19/10" thành "19 10", kể cả khi câu không có vế điều kiện.
- **Cách sửa:** `without_fallback_lead` chỉ đụng vào câu khi thật sự có vế điều kiện, và giữ dấu câu của phần còn lại.

## 5. Sau khi sửa

### 5.1 Hội thoại của 7 case (chế độ chỉ có luật)

Ba lượt định danh đầu giống nhau ở rs-02 đến rs-06 và rs-08 ("Alo" / "Nguyễn Văn A" / "Mười bốn tháng ba năm
một nghìn chín trăm bảy mươi tám"). Bot xác minh xong thì đọc lịch: "Lịch khám Nội tổng quát của anh chị là
3 giờ 30 chiều thứ Tư ngày 14 tháng 10 tại Vinmec Times City ạ. Anh chị có đến khám được theo lịch này không ạ?"

**qc-rs-02** — RESCHEDULED `slot_91d2`, 1 lần GET /slots

| Lượt | Người gọi | Bot |
| --- | --- | --- |
| 4 | Đổi cho tôi sang 5 giờ chiều ngày 14 | Dạ, em chưa thấy khung giờ đó. Hiện còn khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10; khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10. Ngoài ra còn 7 khung khác. Anh chị chọn khung nào ạ? |
| 5 | Không có thì 3 giờ cũng được | Dạ, em đã đổi lịch khám sang 3 giờ chiều thứ Tư ngày 14 tháng 10 cho anh chị ạ. |

**qc-rs-03** — RESCHEDULED `slot_91d2`

| Lượt | Người gọi | Bot |
| --- | --- | --- |
| 4 | Sáng mai khoảng 9 giờ có được không? | Dạ, thứ Ba ngày 6 tháng 10 đã kín lịch. Gần nhất em còn khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10; khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10. Ngoài ra còn 9 khung khác. Anh chị chọn khung nào ạ? |
| 5 | Vậy 3 giờ chiều ngày 14 cũng được | Dạ, em đã đổi lịch khám sang 3 giờ chiều thứ Tư ngày 14 tháng 10 cho anh chị ạ. |

**qc-rs-04** — RESCHEDULED `slot_91d2`. 14:45 không có khung: bot nói rõ, không làm tròn lặng lẽ.

| Lượt | Người gọi | Bot |
| --- | --- | --- |
| 4 | Cho tôi ba giờ kém mười lăm chiều ngày 14 | Dạ, em chưa thấy khung giờ đó. Hiện còn khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10; khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10. … Anh chị chọn khung nào ạ? |
| 5 | Thế ba giờ cũng được | Dạ, em đã đổi lịch khám sang 3 giờ chiều thứ Tư ngày 14 tháng 10 cho anh chị ạ. |

**qc-rs-05** — RESCHEDULED `slot_91d2`

| Lượt | Người gọi | Bot |
| --- | --- | --- |
| 4 | Đổi sang 15h ngày 14/10 | Dạ, chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều. Anh chị đổi sang giờ đó nhé ạ? |
| 5 | Đúng rồi, 15 giờ | Dạ, em đã đổi lịch khám sang 3 giờ chiều thứ Tư ngày 14 tháng 10 cho anh chị ạ. |

**qc-rs-06** — RESCHEDULED `slot_91d2`

| Lượt | Người gọi | Bot |
| --- | --- | --- |
| 4 | Đổi sang ngày 15... à không, vẫn ngày 14 nhưng sớm hơn chút | Dạ, chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều. Anh chị đổi sang giờ đó nhé ạ? |
| 5 | Ừ, 3 giờ được | Dạ, em đã đổi lịch khám sang 3 giờ chiều thứ Tư ngày 14 tháng 10 cho anh chị ạ. |

**qc-rs-07** — RESCHEDULED `slot_91d2` sau 2 lượt

| Lượt | Người gọi | Bot |
| --- | --- | --- |
| 1 | Alo, tôi là Nguyễn Văn A, sinh 14/3/78, tôi muốn đổi lịch sang sớm hơn trong chiều ngày 14 | Dạ, chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều. Anh chị đổi sang giờ đó nhé ạ? |
| 2 | Vâng, 3 giờ được | Dạ, em đã đổi lịch khám sang 3 giờ chiều thứ Tư ngày 14 tháng 10 cho anh chị ạ. |

**qc-rs-08** — TRANSFERRED · PATIENT_REQUEST. Không có lệnh reschedule; lịch cũ giữ 15:30 14/10.

| Lượt | Người gọi | Bot |
| --- | --- | --- |
| 4 | Tôi muốn đổi lịch | Dạ, lịch trống gần nhất có khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10; khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10. Anh chị chọn khung nào, hoặc muốn đổi sang ngày khác ạ? |
| 5 | Không, tôi chỉ đi được 5 giờ chiều thôi | Dạ, em chưa thấy khung giờ đó. Hiện còn khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10; khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10. Ngoài ra còn 4 khung khác. Anh chị chọn khung nào ạ? |
| 6 | Không có 5 giờ thì thôi | Dạ, em giữ nguyên lịch cũ của anh chị và xin phép chuyển máy cho nhân viên để tìm giờ phù hợp ạ. |

### 5.2 So với code cũ

"Code cũ" là bản lúc chạy eval mentor (commit `2aa6d34`). Cả hai bản chạy cùng lời người gọi, cùng dữ liệu
mock và cùng đồng hồ.

**7 case của mentor.** Mỗi case chạy ở 3 chế độ model (`test_mentor_reschedule_case`):

| | Code cũ | Sau khi sửa |
| --- | --- | --- |
| Không có model | 0/7 | 7/7 |
| Model trả CHANGE_INTENT ở câu nêu giờ (như log eval) | 0/7 | 7/7 |
| Model timeout | 0/7 | 7/7 |

**Bộ câu held-out.** Câu viết mới, không lấy từ test hay eval nào; kỳ vọng suy ra từ contract:

| Nhóm câu | Kỳ vọng | Code cũ | Sau khi sửa |
| --- | --- | --- | --- |
| Xin giờ khác ở câu đọc lịch ("5 giờ chiều ngày 14 đi em", "Để sang thứ Năm được không em", "Có giờ nào sáng thứ Năm không em?", "Tôi xin chuyển sang chiều thứ Năm", "Chiều 14 tôi rảnh, đổi giúp tôi") | Vào luồng đổi lịch | 1/5 | 4/5 |
| Nhận khung vừa mời ("Được, đổi giúp tôi.", "Ok em", "Vâng, đổi sang giờ đó đi", "Giờ đó được", "Lấy giờ đó đi em", "Ừ ba giờ chiều cũng được", "3 giờ chiều ngày 14 nhé") | Ghi RESCHEDULED, không hỏi thêm | 4/7 | 6/7 |
| Vế điều kiện rồi nhận khung ("Nếu không còn 5 giờ thì 3 giờ cũng được", "Hết 5 giờ rồi thì lấy 3 giờ vậy", "Không có giờ đó thì 3 giờ cũng được em", "Vậy thì 3 giờ") | Ghi RESCHEDULED | 0/4 | 4/4 |
| Đồng ý kèm giờ ở câu chốt ("Đúng rồi, 3 giờ chiều", "Vâng, ba giờ được"); nhắc giờ khung khác ("Đúng rồi, 10 rưỡi") | Ghi / đọc câu chốt khung kia | 1/3 | 3/3 |
| Bỏ đổi lịch ("Thôi, giữ lịch cũ", "Không được thì thôi", "Thôi bỏ đi em", "Vậy thôi em ạ", "Không có thì tôi giữ lịch cũ") | Giữ lịch cũ, chuyển PATIENT_REQUEST | 0/5 | 5/5 |
| Tự sửa ("Đổi sang ngày 16, à không, ngày 15", "Đổi sang 9 giờ, à 10 giờ rưỡi sáng thứ Năm") | Lấy giá trị nói sau cùng | 1/2 (đọc khung ngày 16) | 2/2 |
| "Sớm hơn / muộn hơn" khi seed thêm khung 16:00 ngày 14 ("Đổi sớm hơn được không em", "Cho tôi sớm hơn chút trong ngày 14", "Muộn hơn chút được không") | Lọc theo giờ lịch đang đổi | 0/3 | 3/3 |
| Model timeout ở câu đọc lịch ("5 giờ chiều ngày 14 đi em", "Đổi sang chiều ngày 14", "Thôi tôi muốn hủy") | Như khi không có model | 2/3 | 3/3 |
| **Tổng các nhóm cần sửa** | | **9/32** | **30/32** |
| Thắc mắc giờ ("9 giờ hả em?", "Ơ, không phải 9 giờ à?", "3 rưỡi à?", "Tôi nhớ là 4 giờ cơ mà") | Không đoán là đổi lịch | 4/4 | 4/4 |
| Câu do dự ở câu mời khung ("Ba giờ à, để tôi xem lịch đã", "Chắc vậy", "Sao cũng được", "Ba giờ thì không được, sớm quá", "Vâng nhưng mà tôi sợ không kịp", "Được, à không, thôi để tôi nghĩ") | Không ghi | 6/6 | 6/6 |

Hai nhóm cuối là nhóm an toàn: code cũ đã đúng, và sau khi sửa vẫn giữ nguyên, không có lệnh ghi nào.

## 6. Ghi chú và giới hạn

- **Đổi kỳ vọng eval "bỏ đổi lịch":** `eval/reschedule/cases.csv` R070–R078 và R124 đổi từ KEEP_OLD sang
  TRANSFER:PATIENT_REQUEST, cho khớp kỳ vọng của mentor ở rs-08. R150 (bỏ đặt lịch, inbound) giữ KEEP_OLD, vì
  chưa có lịch cũ để giữ. R075 "tôi đổi ý" vẫn ra "chưa hiểu" và còn trong danh sách fail.
- **Đổi script eval:** `scripts/reschedule_eval.py` chấm lệnh ghi ngay ở câu mời khung là PICK đúng khung,
  không còn tính là ghi sai. SETUP của SLOT_READBACK 2 dùng "khung nào cũng được" để vẫn tới được câu chốt
  (cùng sửa trong `scripts/no_answer_eval.py`).
- **Chưa làm:**
  - **qc-rs-08, lượt 5:** "Không, tôi chỉ đi được 5 giờ chiều thôi" vẫn đọc lại 2 khung khách vừa từ chối. Case
    vẫn pass, vì lượt 6 chuyển máy đúng.
  - **"3 giờ chiều ngày 14 nhé"** ở câu mời khung còn hỏi thêm một câu chốt, vì "nhé" cuối câu được đọc như hỏi lại.
  - **"Chiều 14 tôi rảnh, đổi giúp tôi"** chưa vào luồng đổi lịch: "đổi giúp tôi" không có "sang / qua" theo sau.
- **Không có lời xin thì không đổi lịch:** câu chỉ nêu giờ mà không có lời xin ("Chiều 14 tôi rảnh") ra "chưa
  hiểu". Đây là chủ ý theo §1.1.5.
- **Tầng LLM không đổi gì:** prompt, router ngữ nghĩa, gateway và fallback giữ nguyên. Cả 7 case pass khi không
  có model và khi model timeout.

## 7. File liên quan

- `src/callbot/engine/dialogue/manager.py`:
  - `_slot_choice`, `_direct_pick`, `_write_slot`, `_picked`;
  - `_proposes_other_time`, `_time_proposal_without_model`;
  - `_note_early_intent`, `_early_flow`, `_from_span`;
  - `_give_up`, `_rounds_exhausted`, `_request_criteria`, `_dates_only`.
- `src/callbot/engine/extraction/agreement.py`:
  - `explicit_slot_pick`, `_strip_slot_time`, `_SLOT_COMPLEMENTS`;
  - `_FALLBACK_LEAD`, `without_fallback_lead`;
  - `gives_up_if_unavailable`, `_DROP_CHANGE`.
- `src/callbot/engine/extraction/slot_choice.py`:
  - `requests_time`, `_TIME_REQUEST`, `_TIME_DOUBT`, `_AVAILABILITY`, `_IMPERATIVE_TAIL`;
  - `_corrected_criteria`, `without_corrected_part`;
  - `_RELATIVE`, `_take_relative`, `anchor_relative`, `_matches`.
- `src/callbot/engine/extraction/extractor.py`: `_early_intent`, cách đưa câu vào bước tìm khung và bước đọc đồng ý.
- `src/callbot/engine/extraction/intent.py`: mẫu "động từ dời + giúp / cho / hộ + xưng hô + sang / qua".
- `src/callbot/engine/extraction/schema.py`: `SlotCriteria.relative`, `before`, `after`; `ExtractionResult.early_intent`, `early_request`.
- `src/callbot/engine/session/fsm.py`: `DIRECT_PICK_QUESTION_FOR`, `confirmation_questions`.
- `src/callbot/engine/policy/guardrails.py`: `assert_action_confirmed`, `_question_covers_slot`.
- `src/callbot/engine/session/context.py`: `early_intent`, `early_request` (yêu cầu đổi lịch nói trước khi xác minh).
- `tests/engine/test_mentor_eval_reschedule.py`: 7 case × 3 chế độ model, seed thêm khung, sớm hơn / muộn hơn.
- `tests/engine/test_reschedule_dialogue.py`, `tests/engine/extraction/test_slot_choice.py`,
  `tests/engine/extraction/test_agreement.py`, `tests/engine/extraction/test_self_correction.py`,
  `tests/engine/extraction/test_intent.py`, `tests/engine/test_confirm_dialogue.py`, `tests/engine/test_orchestrator.py`,
  `tests/transports/http/test_calls.py`, `tests/transports/http/test_audio_parity.py`.
- `scripts/reschedule_eval.py`, `scripts/no_answer_eval.py`, `eval/reschedule/cases.csv`.

## 8. Quy trình xác minh

```powershell
python -m ruff check src tests scripts
python -m ruff format --check src tests
python -m pytest -q
python -m pytest tests/engine/test_mentor_eval_reschedule.py -q
```

## 9. Kết quả xác minh cục bộ (2026-10-06)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` | Pass (4242 passed, 23 skipped) |
| `python -m pytest tests/engine/test_mentor_eval_reschedule.py -q` | Pass (29 passed) |
