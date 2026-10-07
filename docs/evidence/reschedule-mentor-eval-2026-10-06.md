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

## 10. Review PR (06/10/2026): kiểm tra và kế hoạch sửa

Reviewer nêu 8 ý về PR này. Mục này ghi kết quả kiểm tra từng ý, nguyên nhân gốc và kế hoạch sửa.
**Chưa sửa code.** Kế hoạch chờ duyệt.

### 10.1 Cách kiểm tra

- Chạy đúng câu ví dụ của reviewer, cùng vài biến thể cùng ý, qua Orchestrator thật trên
  `FakeClinicAPI.mentor_mock()` với đồng hồ 05/10/2026 15:16 (như §3.1). Ý 4 và ý 8 chạy thêm chế độ model timeout.
- Chạy cùng các câu đó trên hai mốc:
  - `origin/main` (`e0c2d47`): commit cha của nhánh này trên git, tức hành vi trước khi có phần đổi lịch mới.
  - `origin/develop` (`6d03e0a`): nguồn của phần lớn code đổi lịch trong nhánh. Nhánh này là main cộng code đổi lịch
    lấy từ develop, cộng các ý thêm từ bản sửa cũ (RC-1 đến RC-9). Trên git, nhánh không chứa các commit của develop.
- Chạy lại `scripts/reschedule_eval.py --baseline`: holdout 113/121, 0 ghi sai, 0 ghi nhầm khung. Bộ eval hiện có
  **không có câu nào** thuộc 8 tình huống này, nên không bắt được lỗi nào, kể cả lỗi ghi nhầm khung ở ý 1.

### 10.2 Kết luận

| # | Ý review | Là bug? | Trên main | Trên develop | Mức độ | Nguyên nhân gốc |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | "Vâng + giờ khác" bị hiểu là đồng ý | Có | Không | Có, 3/4 câu. "vâng thì 5 giờ" chỉ sai ở nhánh này (thêm "thì" vào bổ ngữ chọn khung) | Cao: ghi nhầm khung | RV-1 |
| 2 | Chọn khung của trang trước thì chuyển máy SYSTEM_ERROR | Có | Không | Có | Cao: case fail | RV-2 |
| 3 | Yêu cầu nói trong lượt danh tính mất ngày / giờ dạng số | Có, đúng một phần ví dụ | Không có R-43 | Có | Trung bình: thêm lượt, không ghi sai | RV-4 |
| 4 | Câu hỏi thường bị hiểu là xin đổi giờ | Có | Không | Có | Cao: vào đổi lịch khi khách không xin | RV-3 |
| 5 | "thì thôi" kết thúc việc đổi lịch quá sớm | Có | Sai kiểu khác, nhẹ hơn | Có | Trung bình: case fail, không ghi sai | RV-3 |
| 6 | "khung N" lúc ghi ngay, lúc hỏi thêm | Có, đúng một phần ví dụ | Không (mọi cách đều qua câu chốt) | Có | Thấp: thêm một lượt | RV-3 |
| 7 | `_early_flow` bỏ qua `get_actionable_appointment` | Có | Không có R-43 | Có | Thấp: hiếm gặp, không ghi sai | RV-5 |
| 8 | GET /appointments lặp trong một lượt | Đúng, là vấn đề hiệu năng | 1 lần / lượt | Một phần: 2 lần khi model lỗi. Phần "sớm hơn / muộn hơn" thêm ở nhánh này (`_request_criteria`) làm thành 3–4 lần | Thấp – trung bình: tăng độ trễ lượt | RV-5 |

Phần lớn lỗi **không phải do code viết mới ở nhánh này**: 7/8 ý có sẵn trên develop và đi theo khi lấy code đổi lịch
từ develop sang. So với main thì đều là lỗi mới, vì main chưa có phần đổi lịch này. Develop chỉ là nhánh thử nghiệm,
nên chỉ sửa ở nhánh này.

Nguyên nhân gốc:

| # | Nguyên nhân gốc | Tầng | Ý |
| --- | --- | --- | --- |
| RV-1 | IE bỏ cụm giờ để ra AGREE (RC-3), nhưng Dialogue chỉ đối chiếu giờ đó với **các khung đã đọc khác**. Giờ không khớp khung nào, hoặc khớp một khung chưa đọc, thì vẫn ghi khung đang chốt. | Dialogue | 1 |
| RV-2 | Có hai định nghĩa "khung vừa mời": Dialogue (`_pickable`, gồm mọi trang của yêu cầu) và guardrail (`_question_covers_slot`, chỉ trang vừa đọc). Dialogue gọi lệnh ghi mà guardrail chắc chắn chặn. | Dialogue, guardrail | 2 |
| RV-3 | Nhận diện theo kiểu "câu có chứa cụm X" chứ không theo "cả câu giải thích được", trái nguyên tắc 1 ở §3.3. `requests_time` nhận mọi câu có "muốn" hay có "có … không" ở bất kỳ đâu; `gives_up_if_unavailable` nhận "thì thôi" ở bất kỳ đâu; `explicit_slot_pick` không bỏ được cụm "khung + số đọc bằng chữ", và coi câu không có chữ nào mang dấu ("khung 1") là transcript không dấu. | IE | 4, 5, 6 |
| RV-4 | Vùng danh tính được cắt trên bản đã `clean` (mất dấu câu) rồi mới đưa vào bộ parse. Bộ parse cần "/" và ":" để nhận "20/10", "9:00". | IE | 3 |
| RV-5 | Dialogue không có một điểm đọc lịch chung cho mỗi lượt: mỗi hàm tự gọi GET /appointments, và luồng R-43 đi tắt qua cổng kiểm tra trạng thái. | Dialogue | 7, 8 |

### 10.3 Từng ý: tái hiện và cách sửa

**Ý 1. "Vâng + giờ khác" bị hiểu là đồng ý (RV-1)**

- **Tái hiện:** bot đang chốt khung 15h ngày 14/10. Các câu "vâng, 9 giờ sáng ngày 20", "vâng thì 5 giờ", "vâng,
  ngày 20", "vâng, 8 giờ sáng ngày 20" đều ghi RESCHEDULED `slot_91d2` (14/10 15:00).
- **Trên main:** không ghi; bot tra theo giờ khách vừa nêu ("em chưa thấy khung giờ đó…", hoặc đọc các khung ngày 20).
- **Hành vi đúng:** ở câu chốt khung, câu đồng ý có nhắc giờ / ngày / thứ tự khung chỉ là đồng ý khi giờ đó khớp
  **chính khung đang chốt**.
  - Khớp một khung khác đã đọc: đọc câu chốt của khung đó, như hiện tại.
  - Không khớp khung nào, hoặc khớp một khung chưa đọc: xử lý như cùng câu đó khi không có "vâng", tức là tra theo
    giờ khách vừa nêu, không ghi. Đây cũng là hành vi của main.
  - Căn cứ: R-23 ("không xác định được khách chọn giờ nào" là mơ hồ), R-29 (giờ bot chưa đọc lại thì đọc lại một
    lần), §1.1.5 (không đoán).
- **Cách sửa:** `DialogueManager._slot_readback`, nhánh AGREE. Chỉ gọi `_write_slot` khi câu không nêu thời gian,
  hoặc khung đang chốt nằm trong `choice.slot_ids`. Ngược lại, rơi xuống nhánh `new_time` sẵn có. IE giữ nguyên:
  RC-3 vẫn đúng cho "Đúng rồi, 15 giờ".
- **Test:**
  - 4 câu trên không ghi; "vâng, 8 giờ sáng ngày 20" đọc câu chốt khung 20/10 8:00.
  - Đối chứng: "Đúng rồi, 15 giờ", "Vâng, 3 giờ được" vẫn ghi `slot_91d2`.
  - Thêm các dòng SLOT_READBACK nhãn `NEW_TIME` vào `eval/reschedule/cases.csv`, để script đếm được ghi nhầm khung.

**Ý 2. Chọn khung của trang trước thì chuyển máy SYSTEM_ERROR (RV-2)**

- **Tái hiện:** "Tôi muốn đổi lịch" (trang 1: 14/10 15:00, 15/10 10:30), rồi "khung khác" (trang 2: 15/10 15:30,
  16/10 9:00), rồi "3 giờ chiều ngày 14". `_direct_pick` gọi ghi, guardrail chặn (`CONFIRMATION`), bot chuyển máy
  SYSTEM_ERROR.
- **Trên main:** bot đọc câu chốt khung 14/10 15:00.
- **Hành vi đúng:**
  - Ghi ngay chỉ khi khách chọn một khung của **trang vừa đọc** (R-29: "giờ bot vừa mời"; guardrail đòi câu trả lời
    cho câu hỏi của lượt ngay trước).
  - Khung của trang trước vẫn chọn được, nhưng qua một câu chốt như main. Không bao giờ thành SYSTEM_ERROR.
- **Cách sửa:**
  - Thêm một hàm dùng chung "câu hỏi này có mời khung X không", đặt ở `session/fsm.py` cạnh
    `DIRECT_PICK_QUESTION_FOR`. Guardrail `_question_covers_slot` và `DialogueManager._direct_pick` cùng gọi hàm này,
    để hai bên không lệch nhau nữa.
  - `_direct_pick` thêm điều kiện: khung được chọn nằm trong `presented_slot_ids`.
- **Test:**
  - Trang 1, "khung khác", trang 2, "3 giờ chiều ngày 14": bot đọc câu chốt 14/10 15:00; "đồng ý" thì RESCHEDULED
    `slot_91d2`.
  - Thêm setup "OFFER_SLOTS trang 2" vào `scripts/reschedule_eval.py`. Script tính TRANSFER:SYSTEM_ERROR ngoài kỳ
    vọng là fail.

**Ý 3. Yêu cầu nói trong lượt danh tính mất ngày / giờ dạng số (RV-4)**

- **Tái hiện:**
  - `_without_identity("tôi muốn đổi lịch sang 20/10")` trả "… sang 20 10" (mất ngày). "15:30" thành "15 30", "9:00"
    thành "9 00" (mất giờ).
  - Trọn cuộc gọi: "Tôi là Nguyễn Văn A, sinh ngày 14 tháng 3 năm 1978, muốn đổi lịch sang 9:00 ngày 16". Sau khi xác
    minh, bot đọc 2 khung ngày 16 thay vì đọc câu chốt khung 9:00.
  - Ví dụ "20/10" của reviewer không tới được bước này: bộ đọc ngày sinh coi "20/10" là ngày sinh thứ hai và hỏi lại
    ngày sinh. Đây là lỗi riêng, có từ trước PR (xem 10.5).
- **Hành vi đúng:** lời yêu cầu được lưu lại (R-43) phải ra đúng tiêu chí như khi khách nói nó sau bước xác minh.
- **Cách sửa:**
  - Đồng ý với hướng của reviewer: cắt trên bản còn dấu câu.
  - `without_fallback_lead` chỉ cắt được vế đầu câu. Vì vậy tách phần căn từ của nó thành một hàm trong
    `extraction/text.py`: bỏ các đoạn tìm thấy trên bản `clean` khỏi bản `normalize` (giữ dấu câu), căn theo từng từ.
  - `_without_identity` và `without_fallback_lead` cùng dùng hàm này.
- **Test:**
  - Unit: "… sang 20/10", "… 15:30 ngày 15", "… 9:00 thứ Sáu"; yêu cầu nói trước và sau phần danh tính.
  - Orchestrator: câu "9:00 ngày 16" ở trên phải ra câu chốt khung 16/10 9:00 ngay sau khi xác minh.

**Ý 4. Câu hỏi thường bị hiểu là xin đổi giờ (RV-3)**

- **Tái hiện:** ở câu đọc lịch, 5/10 câu hỏi thường bị đưa vào đổi lịch. Bot báo "… đã kín lịch" rồi mời khung, ở cả
  chế độ chỉ luật lẫn model timeout:
  - "ngày mai tôi có phải nhịn ăn không" (câu lâm sàng, GC-CLIN-01);
  - "mai tôi có cần mang theo giấy tờ gì không";
  - "tôi muốn hỏi ngày mai phòng khám mở cửa lúc mấy giờ";
  - "hôm nay tôi muốn hỏi chút";
  - "sáng mai tôi muốn gọi lại hỏi thêm được không".

  Khách lỡ đáp "ừ, khung 1" là bot ghi đổi lịch, dù khách không hề xin đổi.
- **Trên main:** bot đọc lại lịch hoặc nói "em chưa hiểu".
- **Hành vi đúng:**
  - Ở câu đọc lịch, chỉ coi là xin giờ khác khi **cả câu** chỉ gồm cụm thời gian, lời xin và từ đệm (danh sách cho
    phép, như `_leaves_content`).
  - Câu còn nội dung khác ("phải nhịn ăn", "mang theo giấy tờ", "hỏi", "gọi lại") đi đường cũ: đọc lại lịch, "em chưa
    hiểu", hoặc chuyển máy theo Policy.
  - Căn cứ: contract Bảng 1 ("yêu cầu một thời điểm khác"), §1.1.5.
- **Cách sửa:** viết lại `slot_choice.requests_time` theo kiểu danh sách cho phép trên cả câu:
  - bỏ cụm thời gian, dùng chung bộ bỏ với `explicit_slot_pick`, thêm "khoảng", "tầm";
  - bỏ lời xin: "được không", "có được không", "cho tôi / em / …", "lấy", "muốn (đổi / chuyển) sang", "rảnh", "tiện",
    "đi / đến / khám được", "còn trống";
  - bỏ các từ của khung hỏi chỗ "có / còn … không", động từ dời ("đổi", "dời", "chuyển", "sang", "qua", "để") và từ đệm;
  - còn từ nào khác thì không phải lời xin;
  - câu có cụm lâm sàng của router (`_CLINICAL_REVIEW_CUES`: "nhịn ăn", "kiêng ăn", …) không bao giờ là lời xin;
  - giữ chặn câu thắc mắc (`_TIME_DOUBT`).
- **Test (chế độ chỉ luật và model timeout):**
  - 10 câu âm tính: 5 câu trên, 4 câu thắc mắc ở §5.2, và "chiều thứ Tư tôi có cần đến sớm không". Không câu nào được
    mời khung.
  - 8 câu xin giờ: 5 câu ở §5.2, câu lượt 4 của rs-03, "Muộn hơn chút được không", "Đổi sớm hơn được không em". Vẫn vào
    đổi lịch như hiện tại: 7/8 đạt; "Chiều 14 tôi rảnh, đổi giúp tôi" vẫn trùng ngày giờ của lịch cũ, giữ như §6.

**Ý 5. "thì thôi" kết thúc việc đổi lịch quá sớm (RV-3)**

- **Tái hiện:** ở câu mời khung, "3 giờ chiều thì thôi, lấy khung 2" ra TRANSFERRED · PATIENT_REQUEST, lịch cũ giữ.
- **Trên main:** cũng sai nhưng nhẹ hơn: bot đọc câu chốt khung 3 giờ, tức khung khách vừa bỏ.
- **Hành vi đúng:**
  - Lời bỏ chỉ kết thúc việc đổi lịch khi nó là **vế cuối** của câu: "Không có 5 giờ thì thôi", "thôi vậy em".
  - Sau lời bỏ mà còn lời chọn hoặc giờ mới thì vế sau mới là câu trả lời (R-44: lấy giá trị nói sau cùng).
  - Câu vừa có lời bỏ vừa có lời chọn thì không phải chọn rõ (`explicit_slot_pick` không nhận), nên bot đọc câu chốt
    một lần.
- **Cách sửa:**
  - `agreement.py`: `gives_up_if_unavailable` chỉ trả True khi sau cụm bỏ cuối cùng chỉ còn từ đệm. Thêm hàm lấy vế
    sau cụm bỏ.
  - `extractor.py`: tìm khung trên vế sau đó, như đang làm với vế điều kiện ở đầu câu.
  - `_slot_choice` giữ nguyên thứ tự xét.
- **Test:**
  - "3 giờ chiều thì thôi, lấy khung 2": câu chốt khung 2, "đồng ý" thì RESCHEDULED `slot_b501`.
  - "Vậy thì thôi, cho tôi ngày 20": tra ngày 20.
  - Giữ nguyên rs-08 và các dòng R070–R078, R124 của eval.

**Ý 6. "khung N" lúc ghi ngay, lúc hỏi thêm (RV-3)**

- **Tái hiện:**
  - Ghi ngay: "lấy khung 2", "khung thứ hai", "cái thứ hai", "chọn khung số 2".
  - Hỏi thêm một câu chốt: "khung 1", "khung một", "lấy khung hai".
  - Ví dụ "lấy khung 2" của reviewer không tái hiện: câu này ghi ngay.
  - "khung 1" phải hỏi thêm vì một nguyên nhân khác: câu không có chữ nào mang dấu nên bị coi là transcript không dấu,
    và `explicit_slot_pick` luôn từ chối transcript không dấu.
- **Trên main:** mọi cách nói đều qua câu chốt (thiết kế cũ, trước R-29 v2.1).
- **Hành vi đúng:** mọi cách gọi thứ tự khung cho cùng một kết quả là ghi ngay (R-29), vì chính bot gọi các lựa chọn
  là "khung 1 / khung 2".
- **Cách sửa:**
  - Bỏ đúng những cụm mà `slot_choice` nhận là thứ tự khung (`_ORDINAL`, `_FIRST`, `_LAST`, `_HOUR_ORDINAL`), thay vì
    chỉ thêm "khung" vào `_TIME_ANCHORS`. Như vậy chỉ có một nguồn định nghĩa, phủ cả "cái hai", "phương án hai".
  - Xét "không dấu" trên **phần còn lại** sau khi bỏ cụm thời gian / thứ tự, không xét cả câu.
- **Test:**
  - 6 câu trên đều ghi đúng khung.
  - Âm tính: "khung khác" đọc trang sau; "khung nào cũng được" đọc câu chốt; "khung 3" khi trang chỉ có 2 khung báo
    không có khung đó; "khung 1 à?" không ghi.

**Ý 7 và ý 8. Một lần đọc lịch mỗi lượt, qua cổng trạng thái (RV-5)**

- **Tái hiện ý 7:**
  - Lịch chuyển sang CANCELLED sau lượt 0, khách nói yêu cầu đổi lịch cùng lượt danh tính: bot vẫn mời khung.
  - Lượt sau khách chọn khung thì gateway chặn ghi, bot chuyển SYSTEM_ERROR.
  - Luồng thường chuyển SYSTEM_ERROR ngay khi xác minh xong.
  - Chỉ xảy ra khi lịch đổi trạng thái sau lượt 0, vì lượt 0 đã từ chối mở cuộc gọi cho lịch không còn thao tác được.
- **Tái hiện ý 8:**
  - "Đổi sớm hơn được không em" ở câu đọc lịch: 4 lần GET /appointments trong một lượt.
  - Model timeout + "Sáng mai khoảng 9 giờ có được không?": 3 lần, vì `_proposes_other_time` chạy 2 lần.
  - rs-07 lượt 1 (yêu cầu "sớm hơn" trong lượt danh tính): 3 lần.
  - Đối chứng "Tôi muốn đổi lịch": 1 lần.
  - Main: 1 lần mỗi lượt.
- **Hành vi đúng:**
  - Mỗi lượt, Dialogue đọc lịch tối đa một lần, qua `get_actionable_appointment`. Lịch không còn thao tác được thì
    chuyển SYSTEM_ERROR như luồng thường.
  - Bản đọc chỉ sống trong lượt, không lưu vào phiên. §4.2.2 cho phép giữ bản sao chỉ đọc trong cuộc gọi.
  - Lệnh ghi vẫn tự đọc `version` mới nhất để gửi If-Match, như cũ.
- **Cách sửa:**
  - `SourceRecorder.get_actionable_appointment`: trả bản đã đọc trong lượt nếu có. Registry của lượt đã có sẵn
    `record_appointment`.
  - `_early_flow` gọi hàm này trước `_new_request`.
  - `_offer_slots` (lấy `clinic_id`) và `_request_criteria` (mốc "sớm hơn / muộn hơn") dùng hàm này thay cho
    `self._gateway.get_appointment`.
  - `respond()`: khi model lỗi, tính `_proposes_other_time` một lần rồi truyền xuống `_attendance`.
  - Đồng ý với đề xuất của reviewer (tính mốc một lần mỗi lượt). Đọc qua registry của lượt thì sửa được cả ý 7 và chỗ
    `_offer_slots` đang đọc lịch không qua cổng trạng thái.
- **Test:**
  - Đếm `clinic.calls`: tối đa 1 GET /appointments mỗi lượt ở "Đổi sớm hơn được không em", ở model timeout + "Sáng mai
    khoảng 9 giờ có được không?", ở rs-07 lượt 1, và ở lượt SLOT_TAKEN đề xuất lại.
  - Lịch CANCELLED trước lượt R-43: bot chuyển SYSTEM_ERROR, `slot_reads == 0`, không mời khung.

### 10.4 Thứ tự làm và tiêu chí xong

| Pha | Ý | Lý do thứ tự |
| --- | --- | --- |
| P1 | 1, 2 | Hai lỗi nặng nhất (ghi nhầm khung, SYSTEM_ERROR); sửa nhỏ ở Dialogue và guardrail |
| P2 | 4, 5, 6 | Cùng nguyên nhân RV-3 ở IE; đo trên bộ held-out mới |
| P3 | 3, 7, 8 | R-43 và cách Dialogue đọc lịch; ý 8 đổi đường đọc lịch nên làm sau cùng, không lẫn vào P1, P2 |

Cách làm mỗi pha:

1. Viết test tái hiện các câu của reviewer trước. Các test này phải fail trên code hiện tại.
2. Sửa.
3. Chạy bộ kiểm tra ở §8 cùng các tiêu chí dưới đây, rồi bàn giao để test local trước khi sang pha sau.

**Bộ held-out mới** được viết trước khi sửa, khoảng 30 câu, như §3.4:

- phủ các nhóm ở 10.3, gồm cả nhóm phải đổi hành vi lẫn nhóm phải giữ nguyên;
- kỳ vọng suy từ contract / PRD;
- không lấy câu từ test.

**Tiêu chí xong:**

- 8 tình huống của reviewer cho đúng hành vi ở 10.3, ở chế độ chỉ luật và model timeout.
- 7 case mentor × 3 chế độ model vẫn đạt 7/7 (`tests/engine/test_mentor_eval_reschedule.py`).
- `scripts/reschedule_eval.py --baseline`:
  - holdout không thấp hơn 113/121;
  - 0 ghi sai, 0 ghi nhầm khung;
  - các dòng mới đều đạt.
- Ở câu đọc lịch:
  - 10/10 câu hỏi thường không vào đổi lịch;
  - câu xin giờ đạt không thấp hơn 7/8.
- Mỗi lượt đổi lịch nêu ở 10.3 gọi GET /appointments tối đa 1 lần.
- `ruff check`, `ruff format --check`, `pytest -q` đều qua.

### 10.5 Ngoài phạm vi, ghi nhận

- **Bộ đọc ngày sinh khi một lượt có hai ngày.** Lỗi có từ trước PR.
  - "…sinh 14/3/78, tôi muốn đổi lịch sang 20/10": `read_dob` thấy hai ngày, coi là nhiều giá trị, và bot hỏi lại
    ngày sinh.
  - "Nguyễn Văn A, tôi muốn đổi lịch sang 20/10" ở câu hỏi tên: "20/10" bị đọc như ngày sinh, cuộc gọi chuyển máy
    NOT_UNDERSTOOD.
  - Việc sửa thuộc bước định danh (R-40, SF-03) nên cần duyệt riêng. Hướng đề xuất: chỉ loại ngày đứng sau "đổi /
    sang / qua" khỏi danh sách ứng viên ngày sinh, và chỉ khi có cụm "sinh …" neo ngày còn lại.
- **Câu lâm sàng khi không có model.** Lỗi có từ trước PR.
  - "ngày mai tôi có phải nhịn ăn không" chỉ được nhận là câu lâm sàng khi model trả lời (router
    `CLINICAL_UNRESOLVED`).
  - Không có model hoặc model timeout thì bot đọc lại lịch, không chuyển CLINICAL_QUESTION như GC-CLIN-01.
  - Sau khi sửa ý 4, câu này trở về hành vi của main.
- **Độ phủ eval.** Bộ eval reschedule và bộ held-out ở §5.2 không có nhóm "đồng ý kèm giờ khác", "chọn khung trang
  trước", "câu hỏi thường có ngày giờ". Các dòng eval và test mới ở 10.3 lấp chỗ trống này.

### 10.6 Tiến độ

| Pha | Trạng thái | Kết quả |
| --- | --- | --- |
| P1 (ý 1, 2) | Xong | Xem dưới |
| P2 (ý 4, 5, 6) | Xong | Xem dưới |
| P3 (ý 3, 7, 8) | Xong, chờ test local | Xem dưới |

**P1 (06/10/2026).**

- **Đã sửa:**
  - Ý 1 — `DialogueManager._slot_readback`: câu đồng ý chỉ ghi khi giờ được nêu khớp khung đang chốt (`_names_other_time`).
    Nếu không khớp, bot tra theo giờ vừa nêu như main.
  - Ý 2 — `session/fsm.py`: thêm `question_offers_slot`, dùng chung cho guardrail `assert_action_confirmed` và
    `DialogueManager._direct_pick`. Khung của trang trước đi qua câu chốt.
- **Test:** `tests/engine/test_reschedule_review.py`, 18 ca, chạy ở cả chế độ chỉ luật và model timeout.
  - 10 ca fail trên code trước khi sửa.
  - 8 ca đối chứng (vẫn ghi đúng khung) pass ở cả hai bản.
- **Eval:**
  - Thêm R153–R157 (split `prompt`) và setup `OFFER_SLOTS 2-trang2` vào `scripts/reschedule_eval.py`.
  - Trên code trước khi sửa, các dòng mới bắt được 3 lần ghi sai (R153–R155) và 1 lần SYSTEM_ERROR (R156).
  - Sau khi sửa, cả 5 dòng mới đều đạt.
  - Holdout giữ 113/121, 0 ghi sai, 0 ghi nhầm khung. 8 ca fail là các ca đã fail từ trước.

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` (`PYTHONUTF8=1` trên Windows) | Pass (4260 passed, 23 skipped) |
| `python -m pytest tests/engine/test_mentor_eval_reschedule.py -q` | Pass (29 passed; 7 case mentor đạt ở cả 3 chế độ model) |
| `python scripts/reschedule_eval.py --baseline` | holdout 113/121, unsafe 0, wrong-slot 0, R153–R157 đạt |

**P2 (06/10/2026).**

- **Đã sửa:**
  - Ý 4 — `slot_choice.requests_time`: ngoài lời xin, **cả câu** phải chỉ gồm cụm thời gian, lời xin, khung hỏi chỗ,
    động từ dời và từ đệm (`_TIME_REQUEST_ALLOWED`). Câu còn từ khác ("phải nhịn ăn", "hỏi", "gọi lại") không phải xin
    giờ. Câu được chuẩn hoá như bộ parse (`_prepare`), nên "9h", "20/10" vẫn nhận.
  - Ý 6 — `slot_choice.strip_slot_phrases`: bỏ cụm thời gian (chuyển từ `agreement._strip_slot_time`) và cụm thứ tự
    khung theo đúng các mẫu `extract_slot_choice` nhận (`_ORDINAL`, `_HOUR_ORDINAL`, `_FIRST`, `_LAST`).
    `explicit_slot_pick` xét "không dấu" trên phần còn lại, không xét cả câu. `requests_time` dùng chung hàm này.
  - Ý 5 — `agreement.answer_after_give_up` / `slot_answer`: vế sau cụm bỏ cuối cùng, khi vế đó còn nội dung. IE tìm
    khung trên `slot_answer`, Dialogue tra giờ mới trên cùng phần đó. `DialogueManager._gives_up`: bỏ đổi lịch khi cụm
    bỏ là vế cuối, hoặc vế sau không nêu khung / giờ nào ("thôi khỏi, tôi đi khám chỗ khác").
  - `text.drop_leading_words`: cắt từ đầu câu trên bản giữ dấu câu. `without_fallback_lead` dùng lại hàm này; P3 dùng
    tiếp cho ý 3.
- **Test:**
  - Thêm 52 ca vào `tests/engine/test_reschedule_review.py` (ý 4, 5, 6; chế độ chỉ luật và model timeout).
  - Thêm unit test cho `requests_time` và `strip_slot_phrases` vào `tests/engine/extraction/test_slot_choice.py`.
  - **Đổi bước dựng của test cũ.** 14 bước dựng trong `test_reschedule_dialogue.py`, `test_confirm_dialogue.py`,
    `test_dialogue_variants.py`, `test_output_guard_flow.py`, `test_silence_line_signal.py` dùng "khung 1" / "khung 2"
    để tới câu chốt của luồng đổi lịch outbound. Các test này dựa vào chính lỗi ở ý 6: câu không có chữ mang dấu nên
    không được ghi ngay.
    - Giờ "khung 1" là chọn rõ nên ghi ngay (R-29 v2.1), vì vậy bước dựng đổi thành "khung N được không". Đây là câu
      hỏi đuôi, nên bot vẫn đọc câu chốt.
    - Phần kiểm tra của các test giữ nguyên.
  - `test_nearest_and_latter_pick_from_the_page`: "lấy cái sau đi" giờ được ghi ngay, giống "cái đầu tiên" vốn đã ghi
    ngay từ trước. Đặt lịch inbound vẫn luôn đọc câu chốt (§1.1.10), không đổi.
- **Held-out P2:** 30 câu viết mới, chạy ở chế độ chỉ luật và model timeout; kết quả hai chế độ như nhau.

  | Nhóm | Trước | Sau |
  | --- | --- | --- |
  | Câu hỏi thường có ngày giờ ở câu đọc lịch, không được vào đổi lịch | 6/8 | 8/8 |
  | Xin giờ khác ở câu đọc lịch | 7/8 | 7/8 |
  | Lời bỏ rồi lời chọn: vế sau là câu trả lời | 2/3 | 3/3 |
  | Lời bỏ ở cuối câu: giữ lịch cũ, chuyển máy | 3/3 | 3/3 |
  | Mọi cách gọi thứ tự khung: ghi ngay | 1/5 | 5/5 |
  | Gọi khung dạng câu hỏi: không ghi | 3/3 | 3/3 |

  Câu xin giờ còn fail là "Tôi muốn sang tuần sau". Lịch hiện tại (14/10) nằm trong tuần sau, nên câu này trùng lịch
  cũ; kết quả này giống trước khi sửa.
- **Eval:**
  - Thêm R158–R160.
  - Holdout giữ 113/121, 0 ghi sai, 0 ghi nhầm khung. R153–R160 đều đạt.

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest -q` (`PYTHONUTF8=1` trên Windows) | Pass (4323 passed, 23 skipped) |
| `python scripts/reschedule_eval.py --baseline` | holdout 113/121, unsafe 0, wrong-slot 0, R153–R160 đạt |

**P3 (07/10/2026).**

- **Đã sửa:**
  - Ý 3 — `text.remove_words`: bỏ các đoạn tìm thấy trên bản `clean` khỏi bản `normalize`, căn theo từ, giữ dấu câu.
    `_without_identity` dùng hàm này, nên "14:00", "15:30", "20/10" trong lời yêu cầu được giữ nguyên.
  - Ý 7, 8 — `SourceRecorder.get_actionable_appointment` trả bản đã đọc trong lượt nếu có, và vẫn kiểm trạng thái.
    Registry chỉ sống trong lượt, không lưu vào phiên.
    - `_early_flow` đọc lịch qua cổng này trước khi mời khung.
    - `_offer_slots` (lấy `clinic_id`) và `_request_criteria` (mốc "sớm hơn / muộn hơn") đọc qua cổng này thay cho
      `self._gateway.get_appointment`.
    - `respond()` tính `_proposes_other_time` một lần khi model lỗi rồi truyền xuống `_attendance`.
    - Lệnh ghi vẫn tự đọc `version` mới nhất làm If-Match.
- **Kết quả trên các câu tái hiện:**

  | Tình huống | Trước | Sau |
  | --- | --- | --- |
  | "…sinh ngày 14 tháng 3 năm 1978, muốn đổi lịch sang 14:00 ngày 16" | đọc 2 khung ngày 16 | câu chốt khung 16/10 14:00 |
  | Lịch CANCELLED sau lượt 0, yêu cầu đổi lịch nói cùng lượt danh tính | mời khung; lượt sau SYSTEM_ERROR | SYSTEM_ERROR ngay khi xác minh xong, không đọc /slots |
  | GET /appointments: "Đổi sớm hơn được không em" | 4 | 1 |
  | GET /appointments: model timeout + "Sáng mai khoảng 9 giờ có được không?" | 3 | 1 |
  | GET /appointments: rs-07 lượt 1 | 3 | 1 |

  Ví dụ "20/10" ở lượt danh tính vẫn bị bộ đọc ngày sinh chặn trước. Lỗi này nằm ngoài phạm vi (10.5).
- **Test:**
  - Thêm 7 ca vào `tests/engine/test_reschedule_review.py`.
  - Thêm 3 unit test cho `remove_words` / `drop_leading_words` (`tests/engine/extraction/test_text.py`).
  - Thêm 3 unit test cho bản đọc lịch dùng lại trong lượt (`tests/engine/policy/test_sources.py`).

**Đối chiếu tiêu chí xong (10.4), sau P1–P3:**

| Tiêu chí | Kết quả |
| --- | --- |
| 8 tình huống của reviewer, chế độ chỉ luật và model timeout | Đạt, trừ ví dụ "20/10" của ý 3 (lỗi bộ đọc ngày sinh, 10.5) |
| 7 case mentor × 3 chế độ model | 7/7 |
| `reschedule_eval.py --baseline` | holdout 113/121, 0 ghi sai, 0 ghi nhầm khung, R153–R160 đạt |
| Câu hỏi thường ở câu đọc lịch không vào đổi lịch | 8/8 (held-out P2) và 6/6 (câu của reviewer) |
| Câu xin giờ vẫn vào đổi lịch | 7/8, bằng trước khi sửa |
| GET /appointments mỗi lượt đổi lịch | 1 |
| `ruff check src tests scripts`, `ruff format --check src tests` | Pass |
| `python -m pytest -q` (`PYTHONUTF8=1`) | Pass (4338 passed, 23 skipped) |

## 11. Merge main (07/10/2026): conflict logic và cách gộp

Nhánh fix hủy / xác nhận (`fix/qc-cancel-identity-flows`, PR #93 và #95) vào main trước, nên PR này conflict khi vào
main. Đã merge `origin/main` (`6e706a0`) vào `fix/t10-reschedule` và gộp lại logic của hai bên.

### 11.1 Cách kiểm tra

- Merge thử trong worktree tạm, chỗ conflict giữ cả hai bên, rồi chạy toàn bộ test. Chạy lại cùng bộ test trên main
  riêng và trên nhánh riêng (`f93c63d`) để tách lỗi do merge với lỗi có sẵn.
- Git báo conflict ở 8 file. Bản merge làm **17 test engine fail**; main riêng và nhánh riêng đều không fail test
  engine nào. 17 test speech / audio fail như nhau ở cả ba bản: `.venv` local thiếu gói `soxr`, không liên quan.
- Chạy thêm các câu nói ở bước danh tính và bước chọn khung trên cả ba bản.

### 11.2 Conflict logic và cách sửa

Ba trong bốn chỗ dưới đây nằm trong phần Git **tự merge được**, nên không hiện ra khi resolve conflict.

| # | Chỗ | Hai bên | Triệu chứng trên bản merge | Cách sửa |
| --- | --- | --- | --- | --- |
| M1 | `SlotCriteria.before` | main: `not_before` / `before` là phút trong ngày ("trước 10 giờ 30"). Nhánh: `before` / `after` là mốc lịch đang đổi ("sớm hơn"). | `_matches` so int với datetime → `TypeError` → chuyển máy SYSTEM_ERROR. "ngày 15 trước 12 giờ", "ngày 14 sớm hơn", qc-rs-06/07 (14/17 test fail). | Giữ tên của main. Hai trường của nhánh đổi thành `earlier_than` / `later_than`. `_dates_only` xoá thêm `not_before` / `before`, nếu không câu "ngày 16 sau 3 giờ chiều" có thể bị báo kín ngày. |
| M2 | `InformationExtractor._intent` | main: `corrected_tail` đọc lại nhu cầu sau "à không / à thôi". Nhánh: R-44 sửa giá trị ("ngày 17 à không 16"). | Phần sau "16 được không" không có nhu cầu → mất RESCHEDULE, bot hỏi lại câu đọc lịch (qc-rs-06 rule / timeout, 4 test). | Chỉ đọc lại nhu cầu trên phần sau khi câu **không** phải lời sửa giá trị (`without_corrected_part(...) == transcript`). |
| M3 | `extract_slot_choice` | main: `_corrected` ("không phải X mà là Y", "Y chứ không phải X") và `_EXCLUSION`. Nhánh: `_corrected_criteria` (R-44). | Không test nào bắt: "3 giờ chiều à không phải 10 giờ 30" (ASR không dấu câu) bị đọc là **loại** 10:30, bot đọc lại 15:00. `_corrected` trả bản `clean`, nên "không phải 14/10 mà là 15/10" mất ngày (cùng loại lỗi với ý 3). | Lời tự sửa xét trước, có lời tự sửa thì không coi "không phải" là loại trừ. `_corrected` cắt trên bản giữ dấu câu (`drop_leading_words`, `keep_leading_words` mới). `parse_slot_criteria` áp `_corrected`, nên Dialogue tạo yêu cầu mới cũng đọc đúng phần giữ lại. Lời sửa giờ: buổi của giờ cũ vẫn giữ ("2 giờ chiều, à nhầm, 3 giờ" = 15:00), trừ khi thành giờ ngoài ngày làm việc ("3 giờ chiều, à không phải, 10 giờ 30" = 10:30, không phải 22:30). |
| M4 | Yêu cầu nói ở bước danh tính | main (QC qc-cn-08): `deferred_intent` → `ctx.early_cancel` → hỏi thẳng câu xác nhận hủy. Nhánh (R-43): `early_intent` → `ctx.early_intent` → mời khung. | Hai test fail vì hai bên quyết định ngược nhau (11.3). Hai chỗ lưu không xoá nhau và `_verify` xét đổi lịch trước, nên khi cả hai cùng được giữ thì đổi lịch luôn thắng (trái R-44). | Gộp về một cơ chế, xem dưới. |

**M4, cơ chế gộp:**

- IE: `_deferred_cancel` của main thành `_deferred_request`, trả CANCEL (kèm lý do) hoặc RESCHEDULE (kèm
  `ExtractionResult.deferred_request`: lời yêu cầu đã bỏ tên và ngày sinh, giữ dấu câu).
  - Yêu cầu đổi lịch đã quyết thì được giữ; câu hỏi lịch sự "… được không" vẫn là yêu cầu.
  - Câu ngập ngừng, chưa quyết hoặc kể lại (`undecided_request`) thì là NONE có span: bỏ yêu cầu đã giữ.
- Bỏ `_early_intent`, `_EARLY_INTENTS`, `ExtractionResult.early_intent` / `early_request` của nhánh, cùng
  `CallContext.early_intent` / `early_request`. Các khoá phiên này chưa từng lên main nên không cần giữ tương thích.
- Dialogue: `_keep_early_request` thay `_keep_early_cancel` và `_note_early_intent`.
  - Phiên giữ **một** yêu cầu: `early_cancel` (main) hoặc `early_reschedule` (mới). Lượt sau thay lượt trước.
  - `_verify` rẽ nhánh theo yêu cầu đang giữ. `_early_reschedule` thay `_early_flow` và vẫn đọc lịch qua cổng
    kiểm trạng thái (ý 7).
- Tên hàm / trường cũ ở RC-8, mục 7 và 10.6 là tên trước khi merge.

**Conflict chỉ trùng dòng, giữ cả hai:**

- `respond()`: `_time_proposal_without_model` của nhánh, rồi điều kiện `_states_other_need` của main. Khi model lỗi
  thì `need_over_conflict` luôn False, nên hai phần không ảnh hưởng nhau.
- `intent._match`: chặn NOT_PATIENT khi người gọi tự nói về mình (main) và `_MOVE_PATTERN` (nhánh) độc lập với nhau.
- Import trong `extractor.py`; comment chuyển trạng thái trong `fsm.py`; test thêm cùng chỗ trong `test_agreement.py`,
  `test_slot_choice.py`.

### 11.3 Hai quyết định ở M4

- **Hủy nói cùng lượt danh tính: theo main (qc-cn-08).** Lượt danh tính là lượt yêu cầu, lượt sau là lượt xác nhận,
  nên vẫn đủ hai lượt của SF-05. Test của nhánh `test_a_cancel_request_in_the_identity_turn_is_not_carried` đổi thành
  `..._asks_the_cancel_confirmation`.
- **"Đổi ý rồi, đổi lịch sang tuần sau" sau một yêu cầu hủy: theo R-43.** Xác minh xong thì mời khung, không hỏi xác
  nhận hủy, không ghi gì. Ca này tách khỏi test của main thành
  `test_switching_to_a_reschedule_at_the_identity_step_replaces_the_kept_cancel`.
- Như yêu cầu hủy của main, lời xin đổi ở lượt chưa có ngày sinh cũng được giữ. Lượt đó vẫn dùng lượt hỏi lại (R-40).

### 11.4 Kết quả

**Các câu kiểm tra ở bước mời khung** (chế độ chỉ luật; cột "Sau khi gộp" chạy thêm model timeout, kết quả như nhau):

| Câu | main | Nhánh | Merge thô | Sau khi gộp |
| --- | --- | --- | --- | --- |
| "ngày 15 trước 12 giờ" | đọc lại 15/10 10:30 | báo chưa thấy khung | SYSTEM_ERROR | đọc lại 15/10 10:30 |
| "ngày 14 sớm hơn" | đọc lại 14/10 15:00 | 14/10 15:00 | SYSTEM_ERROR | 14/10 15:00 |
| "3 giờ chiều à không phải 10 giờ 30" | đọc lại 15:00 (sai) | báo chưa thấy khung | đọc lại 15:00 (sai) | đọc lại 15/10 10:30 |
| "3 giờ chiều, à không phải, 10 giờ 30" | đọc lại 15:00 (sai) | báo chưa thấy khung | báo chưa thấy khung | đọc lại 15/10 10:30 |
| "không phải 14/10 mà là 15/10" | hỏi "khung khác hay giữ lịch cũ" | đọc lại 14/10 (sai) | hỏi "khung khác hay giữ lịch cũ" | mời 2 khung ngày 15/10 |
| "khung nào cũng được trừ khung 1", "bỏ khung 1", "không lấy khung 1" | đọc lại khung 2 | đọc lại khung 1 (sai) | đọc lại khung 2 | đọc lại khung 2 |

Không câu nào ghi ngay: lời loại trừ / tự sửa có "không" nên không là chọn rõ (R-29), luôn qua câu chốt.

**Eval offline** (chỉ luật, cùng cấu hình `NAME_FALLBACK_PROVIDER=none`, `SEMANTIC_FALLBACK_ENABLED=false`):

| Eval | main | Nhánh trước merge | Sau merge |
| --- | --- | --- | --- |
| `reschedule_eval.py --baseline` (holdout) | 99/121 | 113/121 | **113/121**, 8 ca fail trùng nhánh |
| ghi sai / ghi nhầm khung (đổi lịch) | 0 / 0 | 0 / 0 | **0 / 0** |
| `confirm_eval.py --baseline` | 122/181 | 112/168 (bộ ca cũ) | **122/181**, danh sách fail trùng main; ghi sai 0 |
| `cancel_eval.py --baseline` (holdout) | 0.7473 | 0.7473 | **0.7473**; ghi sai 0 |
| `identity_eval.py` | 118/201 | 116/201 | **118/201** |
| `no_answer_eval.py --baseline` | 83/83 | 83/83 | **83/83** |

**Test:**

- Thêm `tests/engine/test_reschedule_review.py`: 14 ca (M1, M2, M3; chế độ chỉ luật và model timeout).
- Thêm `tests/engine/extraction/test_slot_choice.py`: khoảng giờ cùng "sớm hơn"; lời tự sửa không phải loại trừ;
  "15/10" giữ dấu.
- Thêm `tests/engine/extraction/test_text.py`: `keep_leading_words`.
- Thêm `tests/engine/extraction/test_implied_cancel.py`: yêu cầu đổi lịch được giữ / không được giữ ở bước danh tính.
- Thêm `tests/engine/test_mentor_eval_reschedule.py`: yêu cầu đổi lịch ở lượt chưa có ngày sinh được giữ qua phiên
  lưu.
- Đổi hai test theo 11.3.

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests` | Pass |
| `python -m pytest tests/engine -q` (`PYTHONUTF8=1`) | Pass (3608 passed, 1 skipped) |
| `python -m pytest -q` (`PYTHONUTF8=1`) | 4655 passed, 15 skipped, 17 fail đều ở speech / audio do `.venv` local thiếu `soxr`, fail như nhau trên main và nhánh trước merge |
| `python -m pytest tests/engine/test_mentor_eval_reschedule.py -q` | Pass; 7 case mentor đạt ở cả 3 chế độ model |

### 11.5 Ngoài phạm vi, ghi nhận

- **"không lấy ngày 14, ngày 15 đi" → bot mời ngày 14.** Đã có sẵn trên main. IE hiểu lời loại trừ, nhưng khi tạo yêu
  cầu mới, Dialogue đọc lại cả câu và lấy ngày đầu tiên. Không ghi gì vì còn câu chốt. Nên sửa riêng: tạo yêu cầu mới
  từ phần người gọi muốn.
- **"Alo" rồi "Nguyễn Văn A, tôi muốn đổi lịch sang thứ Sáu" → chuyển máy NOT_UNDERSTOOD.** Có trên cả main và nhánh:
  tên không được đọc khi cùng lượt có lời yêu cầu mà không có ngày sinh. Lượt "Alo" trước đó đã dùng lượt hỏi lại.
- **Bộ đọc ngày sinh coi ngày thứ hai trong lượt danh tính là một phần ngày sinh (10.5):** ví dụ "14/03/1978, tôi muốn
  đổi sang 20/10". Ngày sinh bị hỏi lại; lời yêu cầu bị bỏ cùng vùng ngày sinh, nên sau xác minh bot mời khung sớm nhất.
