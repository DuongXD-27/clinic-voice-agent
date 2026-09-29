# Plan R-01 — Output Guard

**Owner:** A (Hoàn) · **Ngày:** 28-09-2026 · **Baseline khảo sát:** `main`, `1062041` (đã merge T-12, PR #50).

**Trạng thái:** đề xuất, chưa triển khai. Rev 2 (28-09-2026) sửa theo 7 điểm review, đối chiếu ở §8. Rev 3 (28-09-2026) cập nhật theo T-12, đối chiếu ở §9. Rev 4 (28-09-2026) sửa theo 4 điểm review Rev 3, đối chiếu ở §10. Rev 5 (28-09-2026) sửa theo 3 điểm review Rev 4, đối chiếu ở §11. Rev 6 (28-09-2026) sửa theo 2 điểm review Rev 5, đối chiếu ở §12.

## 1. Mục tiêu và căn cứ

Mọi câu bot sắp nói, dù trả dạng text qua HTTP hay đưa vào TTS để phát qua Phone/LiveKit, phải đi qua **một** chốt kiểm tra đầu ra duy nhất trong core. Chốt này chặn bốn loại vi phạm:

1. Lộ chi tiết lịch hẹn khi chưa xác minh danh tính (SF-03), kể cả trên voicemail.
2. Đọc slot, thời điểm hoặc thông tin lịch **không khớp dữ liệu gốc** do Gateway trả về (SF-02, SF-01 ở phía đầu ra).
3. Nội dung tư vấn lâm sàng (SF-04).
4. Báo thành công (`CONFIRMED`/`CANCELLED`/`RESCHEDULED`/`BOOKED`) khi chưa có bằng chứng API ghi thành công **với đúng status nghiệp vụ** trong chính lượt đó.

Điều kiện hoàn thành: **HTTP và Phone dùng cùng một cơ chế kiểm soát đầu ra**. Transport không có kiểm tra riêng và không có đường vòng qua guard.

Nguyên tắc thiết kế: guard **không tin nội dung tự khai**. Một câu thoại chỉ được nói ra khi (a) biết chắc câu đó do một template đã đăng ký tạo ra và (b) render lại template đó từ dữ liệu gốc của Gateway cho ra đúng nguyên văn.

| Nguồn | Áp dụng cho R-01 |
| --- | --- |
| [Task breakdown](../task-breakdown.md), R-01 và §7 (bất biến 1, 3, 6, 10) | Bốn loại chặn; một core cho hai transport |
| `engine/policy/guardrails.py` | SF-01..SF-05 hiện chặn **ở lệnh ghi**. `assert_no_clinical_advice` có nhưng chưa được gọi |
| `engine/dialogue/templates.py` | Toàn bộ câu thoại là template; 8 hàm gọi `assert_can_disclose` |
| `engine/orchestrator.py` | Hội tụ tại `start_call` / `_process` → `_apply`. Mọi exception trong Dialogue đi vào `_transfer_after_error` |
| `engine/journal.py`, `session/manager.py`, `tools/clinic_gateway.py::_write` | Sau T-12, `_write` kiểm body ở đúng trạng thái đích (`written_ok`) **trước** `journal.succeeded`: một lệnh `SUCCEEDED` luôn có status đúng (reschedule còn phải đúng `new_slot_id`). Status sai, hoặc gửi lại hết lượt mà vẫn chưa rõ → `WriteOutcomeUnknown` → `_block` → `ReconciliationRequired`. `RedisSessionStore.finish_command` **không lưu** `result` (luôn `None`), và khi `SUCCEEDED` thì purge ngay (`CLINIC_COMMITTED`): context, endpoint, payload đều bị xóa. Sau đó `begin_command` nào trong phiên cũng bị `ReconciliationRequired`, và `complete_turn` bắt buộc `ended=True` |
| [T-12](t12-write-recovery.md), [evidence](../evidence/t12-write-recovery.md) | Gửi lại có giới hạn (`WRITE_MAX_SENDS=3`), ngân sách ghi `WRITE_BUDGET_S=4.0` dùng **chung cho mọi lệnh ghi của lượt** (ContextVar `_turn_deadline` gắn với journal). 4 chỗ kiểm status trong `dialogue/manager.py` (dòng 125, 147, 295, 469) đã thừa, bàn giao cho A dọn |
| `tracing/privacy.py`, `tracing/errors.py`, `engine/diagnostics.py` | Allowlist đóng cho component, operation, span field, event, mã lỗi; giá trị chỉ được là scalar |
| [T-04](../evidence/t04-confirm-dialogue.md), [T-05](../evidence/t05-cancel-dialogue.md), [T-08](../evidence/t08-silence-line-signal.md) | Status sai thì đối soát, không chuyển máy. Voicemail không được đọc lịch. Nhắc lại thì đọc lại `question.text` |

## 2. Hiện trạng và khoảng trống

| ID | Khoảng trống | Bằng chứng tại `1062041` |
| --- | --- | --- |
| G-1 | SF-03 chỉ được kiểm bên trong từng template | `templates.done("RESCHEDULED"/"BOOKED", slot)` đọc giờ mà không gọi `assert_can_disclose`. Một `BotAction("Lịch khám của anh chị ở khoa …")` viết thẳng thì không bị gì chặn |
| G-2 | SF-02 chỉ chặn ở lệnh ghi và chỉ kiểm ID | `assert_slot_offered` chỉ nằm trong `gateway.reschedule/book`. Các template nhận `dict` slot/appointment tùy ý, nên truyền slot ID thật kèm `starts_at` đã sửa vẫn đọc ra giờ sai |
| G-3 | SF-04 ở đầu ra là code chết | Không có nơi nào gọi `assert_no_clinical_advice` |
| G-4 | ~~Reschedule báo thành công mà không kiểm status~~ **Đã đóng bởi T-12** | Gateway kiểm `_status_is("RESCHEDULED", new_slot_id=new_slot_id)` trước khi ghi journal. `_slot_readback` vẫn bỏ qua giá trị trả về nhưng không còn nhận được body sai. R-01 không thêm kiểm tra ở Dialogue |
| G-5 | Lỗi render sau khi ghi thành công làm mất kết quả đã biết | Confirm thành công, sau đó `t.confirmed(ctx, written)` ném `KeyError` (Gateway chỉ kiểm `status`, không kiểm `starts_at`). Exception rơi vào `except Exception` → `_transfer_after_error` → `gateway.transfer` → đọc lại version (thêm một request, tốn ngân sách ghi) → `journal.begin` → store đã purge `CLINIC_COMMITTED` nên ném `ReconciliationRequired` → HTTP 409. Không có `/transfer` đè lên (Redis chặn), nhưng `CONFIRMED` đã chắc chắn lại bị báo thành "cần đối soát" và bot không nói gì. (Rev 2–4 mô tả sai là `/transfer` đè `CONFIRMED`) |
| G-6 | Chưa có điểm chặn chung, lời mở đầu nằm ngoài lượt | HTTP và LiveKit đều lấy `action.utterance` thẳng từ orchestrator. `SessionManager.open()` không bind journal, không đặt chỗ lượt và chỉ chuyển state, nên không thể ghi `/transfer` hay lưu một action kết thúc ở bước mở đầu |
| G-7 | Câu báo đổi lịch dùng cụm của đặt lịch | `done("RESCHEDULED")` nói "em đã đặt lịch …". Trong khi đó `tests/engine/test_identity.py` coi "đã đổi lịch" là cụm của `RESCHEDULED` |
| G-8 | Tracing là allowlist đóng | `COMPONENTS`, `OPERATIONS`, `SPAN_FIELDS`, `EVENT_FIELDS`, `_SEMANTIC_FIELDS`, `ERROR_CODES` chưa có mục nào cho guard; giá trị list bị từ chối |

Điểm thuận lợi: cả hai transport đã gọi chung `CallOrchestrator`, và lượt replay của **phiên còn hoạt động** trả lại `BotAction` đã commit. Vì vậy chỉ cần guard chạy **trước commit** là phủ được HTTP, Phone và replay.

Giới hạn replay: lượt kết thúc bị purge ngay khi commit (`ENDED`, hoặc `CLINIC_COMMITTED` → `ENDED`). Gửi lại lượt đó sẽ nhận `CallEnded` / `ReconciliationRequired` từ `_check_retired`, không nhận lại action kết thúc. R-01 không đổi hành vi này và không cam kết replay action kết thúc.

## 3. Thiết kế

### 3.1. Vị trí và điểm gọi

- Module mới thuộc Policy (phạm vi A):
  - `engine/policy/utterances.py`: registry template và ledger.
  - `engine/policy/sources.py`: ghi nhận dữ liệu gốc.
  - `engine/policy/output_guard.py`: các luật và hàm quyết định.
- Chỉ `CallOrchestrator` gọi guard: trong `_process` trước `_apply`/commit (mọi nhánh), và trong `start_call` trước khi `sessions.open` lưu `opening`.
- Transport không import guard. Có test kiến trúc khẳng định điều này.

```text
Transport (HTTP | LiveKit)
  -> CallOrchestrator
       bind: utterance ledger + source registry (per turn)
       chụp đầu lượt (deepcopy): prior_question, ctx.slots
       -> Policy -> Extraction -> Dialogue
            Dialogue đọc Gateway qua SourceRecorder  -> source registry (appointment, slots: deepcopy)
            Gateway ghi                               -> journal entries trong RAM (command + result deepcopy,
                                                         chỉ sau khi store ghi SUCCEEDED thành công)
            template render                           -> ledger (template_id, refs, args, text)
       -> kết thúc lượt (thành công hoặc exception)
            1. Receipt gate (§3.5): PENDING/UNKNOWN? SUCCEEDED? chỉ FAILED?  -> quyết định trước mọi fallback
            2. Chuẩn hóa ctx theo action cuối (§3.2): kết thúc -> question = None
            3. OutputGuard.check(action, ctx)                                 -> PASS | BLOCK | REPLACE
               (OG-0..OG-5 trên utterance, OG-6 toàn vẹn ctx.slots / ctx.question)
               BLOCK/REPLACE: khôi phục slots + chuẩn hóa lại, rồi mới kiểm action mới
       -> _apply -> commit -> transport trả text / TTS
```

### 3.2. Allow-list nguồn gốc utterance (sửa P1-1)

Guard không chấp nhận chuỗi tùy ý. `action.utterance` chỉ hợp lệ khi **khớp nguyên văn** một trong các dạng sau:

| Dạng | Điều kiện |
| --- | --- |
| Hằng tĩnh đã đăng ký | Thuộc `STATIC_UTTERANCES`, là tập hằng có metadata trong `templates.py` (GREETING_*, ASK_*, TRANSFER, SILENCE, HOLD, …) |
| Kết quả renderer đã đăng ký | Có bản ghi trong ledger của lượt này với `text == utterance` |
| Đọc lại câu hỏi trước | Nhánh xin nhắc lại / quay lại: `utterance == prior_question.text`. Nhánh im lặng: `utterance == render("SILENCE_REPROMPT", prior_question.text)`. `prior_question` được chụp (deepcopy) ở **đầu lượt**, trước Dialogue. Việc từng PASS ở lượt trước **không** đủ: metadata được xác định lại và OG-1 áp lại ở lượt hiện tại (xem dưới) |

Mọi dạng khác đều bị chặn với luật **OG-0 `UNREGISTERED_UTTERANCE`**. `BotAction("Lịch khám của anh chị ở khoa Tim mạch…")` viết thẳng sẽ bị chặn dù không chứa ngày giờ.

**Metadata khi đọc lại câu hỏi (sửa review Rev 3, điểm 3).** Ledger chỉ sống trong lượt, nên metadata của câu hỏi cũ được xác định lại theo kiểu fail-closed, không cần persist:

- `prior_question.text` thuộc `STATIC_UTTERANCES` → dùng metadata của hằng đó.
- Ngược lại (câu do renderer tạo ra, ví dụ `attendance_readback`, `offer_slots`, `slot_readback`) → coi như `discloses=True`. Với `SILENCE_REPROMPT`, câu bọc ngoài thừa hưởng `discloses` của câu bên trong.
- OG-1 áp lại theo ngữ cảnh lượt hiện tại: phát lại câu có lịch khi `outcome == "UNREACHABLE"` hoặc khi chưa xác minh thì bị chặn.
- Câu hỏi có tham chiếu slot (`prior_question.slot_id`, hoặc `presented_slot_ids` với `OFFER_SLOTS`) chỉ được đọc lại khi các slot đó vẫn còn trong `ctx.slot_ids`. Dữ liệu slot không thể bị sửa giữa các lượt, nhờ OG-6.

Test tĩnh khóa giả định fail-closed: mọi renderer có kết quả được truyền vào `questions.ask()` đều khai `discloses=True`, hoặc text của nó thuộc `STATIC_UTTERANCES`. Phương án persist nguồn gốc (`template_id`, refs) vào `Question` bị loại vì phải tăng `SCHEMA_VERSION` mà không chặn thêm được trường hợp nào (§6).

**Câu hỏi được commit phải chính là câu đã phát (sửa review Rev 4, điểm 1).** Không thể dùng một điều kiện chung kiểu `question.turn == ctx.turn ⇒ question.text == utterance`: `silence()` và nhánh nhắc lại / quay lại (`manager.py:101, 165, 169`) cập nhật `question.turn` nhưng giữ `text`, và utterance là `SILENCE + text` hoặc chính `text`. Ngoài ra `_decide` có thể để Dialogue `ask()` câu mới rồi Policy `register_understanding` quyết định chuyển máy `NOT_UNDERSTOOD`: câu hỏi mới đã được gán nhưng không bao giờ được phát.

Trước khi guard chạy, orchestrator **chuẩn hóa** câu hỏi theo action cuối cùng, rồi OG-6 kiểm theo đúng một trong ba trường hợp:

| Trường hợp | Nhận biết | Điều kiện OG-6 |
| --- | --- | --- |
| **Kết thúc** | `action.ended` (chuyển máy, UNREACHABLE, báo thành công, và mọi fallback / REPLACE) | Chuẩn hóa: `ctx.question = None`, vì phiên kết thúc và không còn câu nào chờ trả lời. Câu hỏi đặt trong lượt mà chưa được phát sẽ bị bỏ, không bị kiểm. Không so `question` với utterance |
| **Nhắc lại** | Không kết thúc; `question` bằng `prior_question` ở mọi trường trừ `turn`, và `turn == ctx.turn` | `utterance == question.text` (nhắc lại / quay lại) hoặc `utterance == render("SILENCE_REPROMPT", question.text)` (im lặng). Metadata lấy fail-closed như trên |
| **Hỏi mới** | Không kết thúc; `question` khác `prior_question` ở `question_id` / `text` / `action` / `slot_id` | `question.turn == ctx.turn` và `question.text == action.utterance` (đúng cách `questions.ask()` gán) |
| (Không đổi) | Không kết thúc; `question == prior_question` kể cả `turn` | Hợp lệ, ví dụ `HOLD` hay `NOT_UNDERSTOOD` không `ask()` |

Mọi trạng thái khác (ví dụ không kết thúc mà `question` bị sửa `text` giữ `question_id`, hoặc bị xóa) vi phạm OG-6.

**Fallback không được giữ trạng thái đang vi phạm.** Khi action bị thay (BLOCK → chuyển máy, hoặc REPLACE bằng `DONE_SAFE`), orchestrator khôi phục `ctx.slots` từ snapshot của registry và áp chuẩn hóa "kết thúc" ở trên (mọi fallback đều `ended`), **rồi** mới kiểm lại action mới. Không có chuyện chỉ đổi utterance rồi kiểm lại trên cùng `ctx` đang sai. Nếu kiểm lại vẫn trượt thì dùng hằng `t.TRANSFER` / `DONE_SAFE` (§3.6), không đệ quy.

Cách đăng ký:

- Mỗi hàm dựng câu động trong `templates.py` được bọc bằng decorator `@renderer(id, discloses=..., success_outcome=...)`. Decorator ghi `RenderRecord(template_id, refs, args, text)` vào ledger (ContextVar theo lượt, cùng mẫu với `bind_journal`). Khi không bind ledger (unit test gọi template trực tiếp), decorator chỉ render.
- Các chỗ đang ghép chuỗi trong Dialogue được đưa vào renderer:
  - `f"{t.SILENCE} {question.text}"` → `SILENCE_REPROMPT`.
  - `prefix + offer_slots` → `prefix` chỉ được nhận giá trị trong tập riêng `SLOT_PREFIXES = {"", SLOT_TAKEN, SLOT_NO_MATCH, SLOT_AMBIGUOUS}`, **không** phải bất kỳ hằng đã đăng ký nào. Nếu không, `DONE_SAFE["CONFIRMED"]` dùng làm prefix sẽ render lại vẫn khớp, và lời "đã xác nhận" lọt qua OG-5 vì `offer_slots` không có `success_outcome`.
- Tham số chuỗi của renderer được khai báo miền giá trị trên decorator (`@renderer(..., str_args={"prefix": SLOT_PREFIXES})`). Decorator raise khi render ngoài miền, và guard kiểm lại trên `record.args` (OG-0).
- Metadata `discloses` và `success_outcome` nằm trên template, không suy từ text.

### 3.3. Render lại từ dữ liệu gốc (sửa P1-2)

Guard không tin `spoken` hay `dict` mà template nhận được. Với mỗi `RenderRecord` có `discloses=True`:

1. **Refs, không dùng dict.** Record lưu `refs = [(APPOINTMENT, appointment_id), (SLOT, slot_id)…]` cùng các tham số không phải nguồn (ví dụ `prefix`).
2. **Source registry.** Dữ liệu gốc được lấy từ các nguồn:
   - Slot: **snapshot của registry, không phải `ctx.slots`** (sửa review Rev 3, điểm 1). `list_open_slots()` chỉ trả shallow copy (`list(ctx.slots)`), còn `ctx.find_slot()` trả thẳng dict trong `ctx.slots`. Nếu Dialogue sửa `slot["starts_at"]` tại chỗ, cả dữ liệu render lẫn dữ liệu đối chiếu cùng bị sửa và OG-3 vẫn PASS. Vì vậy registry giữ hai snapshot `deepcopy`:
     - **đầu lượt**: `ctx.slots` vừa nạp từ store, chụp trước khi Dialogue chạy;
     - **sau mỗi lần gọi** `list_open_slots` qua `SourceRecorder`: chụp ngay khi Gateway trả về. Snapshot này thay snapshot trước, giống cách Gateway thay toàn bộ `ctx.slots`.
   - Appointment đọc trong lượt: A thêm lớp `SourceRecorder` bọc các lời gọi `gateway.get_actionable_appointment` và `gateway.list_open_slots` trong Dialogue. Lớp này `deepcopy` kết quả **ngay khi Gateway trả về**, trước khi Dialogue kịp dùng.
   - Sau ghi: lấy từ **receipt trong RAM của `StoreCommandJournal`** (sửa review Rev 4, điểm 2), không lấy từ store. `RedisSessionStore.finish_command()` luôn ghi `result=None`, và khi `SUCCEEDED` thì `_purge_state(CLINIC_COMMITTED)` xóa context/turn. Vì vậy store không bao giờ giữ được dữ liệu receipt.
     - `StoreCommandJournal` giữ danh sách `JournalEntry(command, status, result)` của lượt. `begin` thêm entry `PENDING` sau khi `store.begin_command` thành công; `failed` / `unknown` cập nhật status.
     - `succeeded` gọi `store.finish_command(...SUCCEEDED...)` **trước**, và chỉ khi lời gọi này không lỗi mới ghi `deepcopy(command)` và `deepcopy(result)` vào entry. Một receipt thành công chỉ tồn tại khi nhật ký bền vững đã ghi nhận `SUCCEEDED`. Nếu store lỗi thì `SessionStoreUnavailable` đi đường `TURN_ABORTING_ERRORS` như hiện nay, không có receipt.
     - Helper `journal.entries()` là nguồn duy nhất cho receipt gate và OG-5. Protocol `CommandJournal` thêm phương thức đọc này; `bind_journal` giữ nguyên.
     - `deepcopy` tách receipt khỏi dict `written` mà Gateway trả cho Dialogue.
   - **Toàn vẹn trước commit (OG-6).** `ctx.slots` phải bằng snapshot slot mới nhất của registry. Một lần sửa tại chỗ, dù không được đọc ra trong lượt, cũng bị chặn trước khi được lưu. Như vậy slot nạp từ store ở đầu lượt sau luôn là dữ liệu Gateway gốc.
3. **Kiểm ref.** Slot ref phải thuộc slot ID của snapshot; nếu template là đề xuất hoặc đọc lại thì còn phải thuộc `presented_slot_ids`/`selected_slot_id`. Appointment ref phải thuộc {`target_appointment_id`, `created_appointment_id`}.
4. **Ràng buộc template thành công với receipt** (sửa review Rev 3, điểm 2). Outcome khớp là chưa đủ: sau khi ghi slot A, `BOOKED_DONE` render slot B (B cũng có nguồn) sẽ báo sai lịch vừa ghi. Refs của template có `success_outcome` phải trùng đối tượng trong receipt của lệnh ghi đó:

   | Template | Ref bắt buộc |
   | --- | --- |
   | `RESCHEDULED_DONE` | slot ref == `command.payload["new_slot_id"]` == `result["new_slot_id"]` |
   | `BOOKED_DONE` | slot ref == `command.payload["slot_id"]`; appointment (nếu có) == `result["appointment_id"]` |
   | `CONFIRMED_DONE` | appointment ref == appointment trong endpoint của command; dữ liệu render lấy từ `result` của receipt |
   | `CANCELLED_DONE` | không nói chi tiết, chỉ cần receipt |

   Sai ràng buộc thì vi phạm OG-5. Vì đã có receipt hợp lệ, xử lý là REPLACE bằng `DONE_SAFE[outcome]` (§3.5), không chuyển máy.
5. **Render lại.** Guard gọi lại đúng renderer đó với dữ liệu lấy từ registry theo ref, cùng `args` cũ. Kết quả phải **bằng nguyên văn** `record.text`. Slot ID thật nhưng `starts_at` đã bị sửa (kể cả sửa tại chỗ trong `ctx.slots`) sẽ cho ra text khác, nên bị chặn (OG-3).

Yêu cầu kèm theo: renderer phải là hàm thuần của (dữ liệu nguồn, args). `ctx` chỉ được dùng để assert. Có test khóa tính thuần: render hai lần cho kết quả giống nhau.

Không cần GW (phạm vi B) thay đổi: `SourceRecorder` nằm ở tầng Dialogue, và journal là của F-03 (A). Protocol `CommandJournal` chỉ thêm `entries()`; Gateway không gọi phương thức này.

### 3.4. Luật kiểm tra

| Mã | Luật | Mã lỗi |
| --- | --- | --- |
| OG-0 | Utterance không thuộc allow-list §3.2, hoặc tham số chuỗi của renderer nằm ngoài miền khai báo (ví dụ `prefix` ∉ `SLOT_PREFIXES`) | `OUTPUT_UNREGISTERED` (mới) |
| OG-1 | Template (hoặc câu hỏi được đọc lại, theo metadata fail-closed §3.2) có `discloses=True` khi `not ctx.identity_verified`, hoặc khi `action.outcome == "UNREACHABLE"` (voicemail / không nghe máy) | SF-03 |
| OG-2 | Appointment ref ngoài {target, created} | SF-01 |
| OG-3 | Slot ref không có nguồn, hoặc render lại ra text khác (§3.3) | SF-02 |
| OG-4 | `assert_no_clinical_advice(utterance)`, mở rộng marker vừa phải. Chạy thêm trên mọi hằng/renderer trong test để chống false positive | SF-04 |
| OG-5 | Template có `success_outcome` X thì bắt buộc `action.outcome == X`, receipt gate (§3.5) xác nhận X, **và** refs trùng đối tượng trong receipt (§3.3 bước 4). Ngược lại, `action.outcome` thuộc nhóm thành công thì utterance phải do template có `success_outcome` tương ứng tạo ra | `OUTPUT_UNPROVEN_SUCCESS` (mới) |
| OG-6 | Toàn vẹn trạng thái trước commit, sau khi chuẩn hóa: `ctx.slots` khác snapshot slot mới nhất của registry; hoặc `ctx.question` không thuộc trường hợp hợp lệ nào (kết thúc / nhắc lại / hỏi mới / không đổi, §3.2) | Slot: SF-02; câu hỏi: `OUTPUT_UNREGISTERED` |

Không còn dùng regex ngày giờ làm luật chính. Allow-list cộng render lại đã bao trùm trường hợp đó.

### 3.5. Receipt gate: kết quả ghi đi trước mọi fallback (sửa P1-3, P1-4)

Định nghĩa **lệnh ghi đóng** là các thao tác `confirm→CONFIRMED`, `cancel→CANCELLED`, `reschedule→RESCHEDULED`, `book→BOOKED`, `transfer→TRANSFERRED`, `unreachable→UNREACHABLE`. Từ T-12, journal chỉ ghi `SUCCEEDED` khi body đã ở đúng trạng thái đích. Gate vẫn đọc `result.status` từ receipt để lấy outcome, và assert lại status như một lớp phòng thủ rẻ, không phải kiểm tra chính.

Gate chạy ở cuối `_process`, **trước** `_transfer_after_error` và trước guard, cho cả nhánh thành công lẫn mọi nhánh exception. Gate đọc `journal.entries()` (§3.3) và **phân biệt số lệnh đã thử với số lệnh thành công** (sửa review Rev 4, điểm 3). Một lượt hợp lệ có thể chứa nhiều lệnh: luồng `unreachable()` bị từ chối (`FAILED`) rồi chuyển sang `transfer(SYSTEM_ERROR)` (`SUCCEEDED`) trong cùng lượt (`manager.py:133-146`). Gate xét theo thứ tự ưu tiên:

| # | Trạng thái các lệnh của lượt | Hành vi |
| --- | --- | --- |
| 1 | Có lệnh `PENDING` hoặc `UNKNOWN` | **Chặn ghi tiếp, đi đường đối soát.** Nếu exception đang bay là `TURN_ABORTING_ERRORS` thì để nó đi tiếp như hiện nay. Nếu không (lỗi khác, hoặc Dialogue lỡ nuốt lỗi) thì `raise WriteOutcomeUnknown`, **không** gọi `_transfer_after_error`. `SessionManager` → `_block` → `ReconciliationRequired` |
| 2 | Có đúng **một** lệnh `SUCCEEDED` (có thể kèm các lệnh `FAILED` trước đó) | Receipt = lệnh `SUCCEEDED`. **Cấm chuyển máy / ghi thêm.** Action được giữ chỉ khi thỏa **đủ** các điều kiện: `ended=True`, `state == "ENDED"`, `outcome` == outcome của receipt, lý do khớp receipt (`transfer_reason` == `command.payload["transfer_reason"]` với TRANSFERRED; `unreachable_reason` == `command.payload["unreachable_reason"]` với UNREACHABLE), và guard PASS. Thiếu bất kỳ điều kiện nào, hoặc đang có exception, thì thay bằng action an toàn: `utterance` là hằng tĩnh không chi tiết `DONE_SAFE[outcome]` (TRANSFERRED dùng `t.TRANSFER`, UNREACHABLE dùng `t.GOODBYE_UNREACHABLE`), `ended=True`, `state="ENDED"`, outcome và lý do lấy từ receipt, trace `output_guard.replaced`. Ví dụ `unreachable: FAILED` + `transfer: SUCCEEDED` → receipt `TRANSFERRED`, action `t.TRANSFER` qua guard bình thường |
| 3 | Có từ hai lệnh `SUCCEEDED` trở lên | Bất thường: trên Redis, lệnh `SUCCEEDED` đầu tiên đã purge `CLINIC_COMMITTED`, nên `begin_command` sau đó luôn bị `ReconciliationRequired`. Xử lý như chưa rõ: `raise WriteOutcomeUnknown` |
| 4 | Chỉ có lệnh `FAILED` (từ chối xác định) | Được fallback: nhánh bình thường qua guard (ví dụ `unreachable` bị từ chối → transfer mà `/transfer` cũng bị từ chối → vẫn `TRANSFERRED`, theo `transfer()`); nhánh lỗi dùng `_transfer_after_error` như hiện tại |
| 5 | Không có lệnh nào | Như hàng 4 |
| — | Receipt `SUCCEEDED` mà `result.status` sai thao tác | Sau T-12 không xảy ra (bug journal/Gateway). Xử lý như hàng 1 |

Vì sao hàng 2 phải bắt buộc đóng phiên, chứ không chỉ khớp outcome: `_apply` chỉ gọi `sessions.close` khi `action.ended`, ngược lại gọi `transition` (`orchestrator.py:348-357`). Trên Redis, lượt có lệnh `SUCCEEDED` phải commit với `ended=True`, nếu không `complete_turn` ném `ValueError` (`redis_store.py:206-214`). Một action `CONFIRMED` đúng câu mà quên `ended=True` sẽ mất phản hồi thành công ngay ở bước commit, dù Clinic đã ghi. Gate bắt trường hợp này **trước** `_apply`, không để `complete_turn` phát hiện.

Việc kiểm status reschedule ở Rev 2 (bước 3 cũ) **bỏ**: T-12 đã làm ở Gateway cho cả 6 thao tác. Gate là lớp phòng thủ thứ hai sau Gateway.

Với G-5, gate hàng 2 giữ `CONFIRMED` thay vì để `_transfer_after_error` đọc lại version, rồi va vào store đã purge và kết thúc bằng 409.

### 3.6. Hành vi khi guard chặn

| Tình huống | Hành vi |
| --- | --- |
| Vi phạm, gate hàng 4/5 (chưa có lệnh thành công) | `raise SevereFailureBlocked(code)` → nhánh sẵn có → `_transfer_after_error(SYSTEM_ERROR)`. Trước khi kiểm lại: khôi phục `ctx.slots`, chuẩn hóa câu hỏi kiểu "kết thúc" (§3.2). Action chuyển máy cũng qua guard; nếu vẫn bị chặn thì dùng hằng `t.TRANSFER`, không đệ quy |
| Vi phạm, gate hàng 2 (đã có receipt) | REPLACE theo §3.5, cùng bước khôi phục / chuẩn hóa |
| Gate hàng 1/3 | Không có fallback nói gì; lượt bị chặn đối soát |
| Vi phạm ở lời mở đầu | Xem §3.7 |

### 3.7. Lời mở đầu (sửa P2-5)

`open()` không có journal và không đặt chỗ lượt, nên ở bước mở đầu **không bao giờ** chuyển máy hay ghi Mock.

- Mọi lời mở đầu hợp lệ phải là hằng tĩnh, `discloses=False`, không outcome (GREETING_OUTBOUND, GREETING_INBOUND, GREETING_HANDOFF_INBOUND).
- Khi guard chặn lời mở đầu, ném `CallStartBlocked(EngineError)` từ bên trong callback `opening`, **trước** `create_session`. Hệ quả: không tạo phiên, không có lời bot/TTS, không ghi Mock. Gửi lại cùng `call_id` sau khi sửa lỗi sẽ mở phiên mới bình thường, giống `OUTBOUND_START_FAILED`.
- HTTP: `_translate_errors` ánh xạ sang `503 CALL_START_BLOCKED` và cập nhật [http-api.md](../reference/http-api.md). LiveKit: exception đi ra khỏi `CallBridge.run()`, `finally` gọi `aclose()`, không phát âm thanh.
- Test tích hợp cho cả hai hướng gọi: ép opening trả câu chưa đăng ký. HTTP trả 503, store không có phiên, recorder của Mock rỗng. `CallBridge._speak` không được gọi.

### 3.8. Câu báo đổi lịch (sửa P2-6)

Tách `done()` thành các renderer riêng, mỗi renderer có `success_outcome`:

| Renderer | Câu thoại | `success_outcome` |
| --- | --- | --- |
| `CONFIRMED_DONE` (= `confirmed`) | "Dạ, em đã xác nhận lịch khám … cho anh chị. Hẹn gặp anh chị ạ." | CONFIRMED |
| `CANCELLED_DONE` | "Dạ, em đã hủy lịch khám cho anh chị ạ." | CANCELLED |
| `RESCHEDULED_DONE` | "Dạ, em đã **đổi lịch** khám sang {giờ} cho anh chị ạ." (đổi từ "đã đặt lịch") | RESCHEDULED |
| `BOOKED_DONE` | "Dạ, em đã đặt lịch {giờ} cho anh chị ạ." | BOOKED |

OG-5 dựa trên metadata template nên hết mâu thuẫn. Thêm một test tĩnh: mọi hằng/renderer chứa cụm "đã xác nhận / đã hủy / đã đổi lịch / đã đặt lịch" (không đứng sau "chưa") phải khai báo đúng `success_outcome`. Câu mẫu `done_resched` trong `scripts/tts_bench_set.py` cập nhật theo.

### 3.9. Tracing và chẩn đoán (sửa P2-7)

| Nơi sửa | Nội dung |
| --- | --- |
| `tracing/privacy.py` `COMPONENTS` | Thêm `GUARD` |
| `tracing/privacy.py` `OPERATIONS` | Thêm `core.output_guard` |
| `tracing/privacy.py` `SPAN_FIELDS` | Thêm `guard_verdict` (PASS/BLOCK/REPLACE), `guard_rule` (OG-0..OG-6), `render_count` (int), `write_attempted` (int, số lệnh ghi đã `begin` trong lượt), `write_succeeded` (int), `write_operation` (enum: thao tác của receipt `SUCCEEDED`, hoặc `NONE`), `write_status_match` (bool). **Không** dùng list. Nhiều lệnh đã thử là bình thường (ví dụ `unreachable` FAILED rồi `transfer` SUCCEEDED); chỉ `write_succeeded > 1` mới bất thường (gate hàng 3) |
| `tracing/privacy.py` `_SEMANTIC_FIELDS` | Thêm `guard_verdict`, `guard_rule`, `write_operation` (regex semantic sẵn có) |
| `tracing/privacy.py` số nguyên | Thêm `render_count`, `write_attempted`, `write_succeeded` vào nhóm kiểm int ≥ 0 |
| `tracing/privacy.py` `EVENT_FIELDS` | `output_guard.blocked`: {`guard_rule`, `error_type`, `error_code`}. `output_guard.replaced`: {`guard_rule`, `outcome`, `write_operation`} |
| `tracing/errors.py` | `ERROR_CODES` và `_GUARDRAIL_CODES`: `GUARDRAIL_OUTPUT_UNREGISTERED`, `GUARDRAIL_OUTPUT_UNPROVEN_SUCCESS`. OG-1..OG-4 dùng lại `GUARDRAIL_SF_0x` |
| `engine/diagnostics.py` `ERROR_CODES` | `OUTPUT_UNREGISTERED`, `OUTPUT_UNPROVEN_SUCCESS`; `classify` nhận code mới |
| Test | `test_tracing_core.py` / `test_tracing_integration.py`: span GUARD được chấp nhận; một thuộc tính ngoài allowlist vẫn bị từ chối. `test_metrics_query.py`: kiểm tra có enumerate component không |

Trace không bao giờ chứa utterance, `spoken`, giờ slot hay ID.

### 3.10. Ngoài phạm vi

- Không thêm LLM/classifier cho SF-04.
- Không đổi schema session. Ledger, source registry và receipts đều chỉ sống trong lượt. Metadata câu hỏi được xác định lại fail-closed (§3.2), không persist. Nếu sau này phải persist, tăng `SCHEMA_VERSION` kèm round-trip test.
- Không sửa Gateway (B), kể cả logic gửi lại và bảng trạng thái đích của T-12. Hai chỗ A sửa là journal (F-03) và `SourceRecorder` ở Dialogue.
- Không xử lý ngắt lời / phát dở (P-03, P-04).

## 4. Các bước triển khai

1. **Registry + ledger** (`policy/utterances.py`): decorator `@renderer` có `str_args`, `STATIC_UTTERANCES`, `SLOT_PREFIXES`, ContextVar ledger. Chuyển mọi template sang đăng ký; tách `done()` (§3.8); đưa chuỗi ghép im lặng / prefix vào renderer. Test: không bind ledger thì hành vi giữ nguyên; renderer là hàm thuần; prefix ngoài `SLOT_PREFIXES` bị từ chối.
2. **Source registry** (`policy/sources.py`): snapshot slot đầu lượt, `SourceRecorder` bọc `get_actionable_appointment` và `list_open_slots` trong `DialogueManager`. **Journal entries trong RAM** (§3.3): `StoreCommandJournal` giữ `JournalEntry` theo từng lệnh; `succeeded` chỉ ghi receipt (`deepcopy` command + result) sau khi `store.finish_command` thành công; thêm `entries()` vào protocol `CommandJournal`.
3. **Dọn kiểm status trùng ở Dialogue** (bàn giao từ T-12): xóa 4 chỗ `written.get("status") != …` trong `dialogue/manager.py` (dòng 125, 147, 295, 469), vì Gateway và receipt gate đã bao. Test T-12 ở tầng Gateway giữ vai trò chứng minh. Có thể tách thành PR riêng nếu đụng T-10/T-11.
4. **Receipt gate** (§3.5) trong `_process`, bọc cả nhánh `SevereFailureBlocked` và `Exception` trước `_transfer_after_error`. Đọc `journal.entries()`, xét theo thứ tự hàng 1 → 5.
5. **OutputGuard** (`policy/output_guard.py`): OG-0..OG-6 dạng hàm thuần, trả `GuardVerdict`. Gồm ràng buộc template thành công ↔ receipt (§3.3 bước 4) và metadata fail-closed khi đọc lại câu hỏi.
6. **Nối vào orchestrator**: bind ledger/registry trong `_process` và trong callback opening; chụp `prior_question` và `ctx.slots` ở đầu lượt; chuẩn hóa câu hỏi theo action cuối (§3.2); xử lý BLOCK/REPLACE kèm khôi phục slot và chuẩn hóa lại (§3.6); `CallStartBlocked` (§3.7).
7. **HTTP**: ánh xạ `CallStartBlocked` sang `503 CALL_START_BLOCKED`, cập nhật `docs/reference/http-api.md`.
8. **Tracing/diagnostics** (§3.9).
9. **Evidence** `docs/evidence/r01-output-guard.md` theo TEMPLATE; cập nhật `docs/evidence/matrix.md`.

## 5. Kế hoạch test

| Nhóm | Ca kiểm | File |
| --- | --- | --- |
| OG-0 | `BotAction` viết thẳng, có hoặc không có ngày giờ ("Lịch khám của anh chị ở khoa Tim mạch") → chặn. Hằng tĩnh / renderer / đọc lại `prior_question.text` / `SILENCE_REPROMPT` → pass. `offer_slots` với `prefix=DONE_SAFE["CONFIRMED"]` (hoặc hằng đã đăng ký bất kỳ ngoài `SLOT_PREFIXES`) → decorator raise và guard chặn | `tests/engine/policy/test_output_guard.py` (mới) |
| OG-1 | Renderer disclose khi chưa xác minh; renderer disclose kèm outcome UNREACHABLE → chặn. **Đọc lại câu hỏi có lịch** (lượt trước là `attendance_readback`/`offer_slots`) với outcome `UNREACHABLE` → chặn, cả dạng nhắc lại lẫn `SILENCE_REPROMPT`. Đọc lại câu hỏi tĩnh không lộ lịch với `UNREACHABLE` → pass. Test tĩnh: mọi renderer đưa vào `ask()` có `discloses=True` hoặc ra hằng tĩnh | cùng file |
| OG-2/OG-3 | Appointment ID lạ. Slot ID ngoài snapshot. **Slot ID thật + `starts_at` đã sửa** → chặn. **Sửa tại chỗ** `ctx.find_slot(id)["starts_at"]` (và phần tử trong list mà `list_open_slots()` trả về) rồi render → chặn, không phải truyền một dict giả riêng. Appointment dict bị sửa sau khi đọc → chặn. Đọc lại `OFFER_SLOTS` khi slot đã được đề xuất không còn trong `ctx.slot_ids` → chặn | cùng file |
| OG-4 | Marker lâm sàng bị chặn; mọi hằng/renderer (kể cả TRANSFER cho `CLINICAL_QUESTION`) pass | cùng file |
| OG-5 / §3.8 | CONFIRMED không receipt → chặn. RESCHEDULED với "đã đổi lịch" → pass. **Ghi A, nói B**: book/reschedule slot A thành công, `BOOKED_DONE`/`RESCHEDULED_DONE` render slot B (cũng có trong snapshot) → REPLACE bằng `DONE_SAFE`, outcome giữ theo receipt, không `/transfer`. `CONFIRMED_DONE` render appointment khác receipt → REPLACE. Test tĩnh cụm thành công ↔ `success_outcome` | cùng file + `tests/engine/test_output_guard_flow.py` |
| OG-6 | Sửa tại chỗ `ctx.slots` mà **không** render → chặn. `ctx.question.text` bị đổi sau `ask()` (khác `action.utterance`) → chặn. `ctx.question` cũ bị sửa `text` trong lượt không hỏi mới → chặn. Với các ca bị chặn, assert **ngay trước `_apply`** (spy trên `_apply` hoặc `sessions.close`): `ctx.slots` đã bằng snapshot gốc và `ctx.question is None`. **Sau commit** chỉ assert phiên đã purge (`purged_reason == "ENDED"`, context `{}`) và gửi lượt tiếp theo nhận `CallEnded`; không đọc slot/câu hỏi từ store vì Redis đã xóa. **Không chặn nhầm** (chạy trên core thật): im lặng → `SILENCE_REPROMPT` với `question.turn` mới → pass; xin nhắc lại / quay lại → pass; im lặng khi `question is None` → pass; `HOLD` → pass (ba ca không kết thúc này kiểm được `ctx.question` từ store ở lượt sau); Dialogue `ask()` câu mới rồi Policy chuyển máy `NOT_UNDERSTOOD` → pass, `ctx.question is None` kiểm trước `_apply` | cùng hai file |
| Receipt gate | (a) Confirm ghi thành công rồi `t.confirmed` ném `KeyError` → outcome `CONFIRMED`, utterance `DONE_SAFE`, Mock **không** có `/transfer`, không có `GET` đọc lại version, HTTP 200 thay vì 409. (a') Như (a) nhưng confirm thành công ở lần gửi lại sau một timeout (`fail_next(..., outcome_unknown=True, apply_first=True)`) → vẫn `CONFIRMED`. (b) Reschedule trả status `SCHEDULED` (`after_next`) → HTTP 409 `CALL_RECONCILIATION_REQUIRED`, không `/transfer`, không nói `RESCHEDULED_DONE`. (c) Confirm ghi thành công + guard chặn nội dung → REPLACE, không `/transfer`. (d) Journal giả có receipt `SUCCEEDED` sai status → `WriteOutcomeUnknown`. (e) **`unreachable` FAILED + `transfer` SUCCEEDED** cùng lượt → `TRANSFERRED`, guard pass, `write_attempted=2`, `write_succeeded=1`. (f) `unreachable` FAILED + `/transfer` cũng bị từ chối → vẫn `TRANSFERRED` (hàng 4). (g) Lệnh còn `PENDING` khi Dialogue ném lỗi thường (journal giả) → `WriteOutcomeUnknown`, **không** gọi `_transfer_after_error`. (h) **Đúng outcome nhưng quên đóng phiên**: confirm thành công, Dialogue (monkeypatch) trả `CONFIRMED_DONE` hợp lệ với `ended=False` → REPLACE bằng `DONE_SAFE["CONFIRMED"]`, `ended=True`, `state="ENDED"`; trên fakeredis `complete_turn` không ném, HTTP 200 `CONFIRMED`. Biến thể: `state` khác `ENDED`; TRANSFERRED với `transfer_reason` khác payload receipt → REPLACE, lý do lấy từ receipt | `tests/engine/test_output_guard_flow.py` (mới) |
| Receipt trên Redis | Chạy (a), (c), (e) với `RedisSessionStore` trên fakeredis (fixture `tests/conftest.py`): sau `finish_command(SUCCEEDED)` store đã purge (`result=None`, payload rỗng) nhưng `journal.entries()` vẫn trả receipt đủ command + result; guard dùng được cho OG-5. Store ném lỗi ở `finish_command` → không có receipt, lượt đi đường `SessionStoreUnavailable` | cùng file |
| Opening | Cả hai hướng: opening chưa đăng ký → HTTP 503 `CALL_START_BLOCKED`, không có phiên, Mock không bị ghi; gửi lại sau khi sửa thì mở bình thường. LiveKit: `_speak` không được gọi | `tests/transports/http/test_calls.py`, `tests/transports/livekit/test_call_bridge_mapping.py` |
| Parity | Cùng kịch bản vi phạm trong lượt: HTTP trả utterance an toàn và `CallBridge._speak` nhận đúng utterance đó | như trên |
| Replay | Phiên còn hoạt động: gửi lại một lượt **không kết thúc** thì nhận action đã guard, guard không chạy lại. Lượt kết thúc: gửi lại nhận `CallEnded` / `ReconciliationRequired` như hiện nay (không đổi) | `tests/engine/session/test_turn_lifecycle.py` |
| Tracing | Span GUARD và hai event mới đi qua `privacy._validate`; trace không chứa text/ID | `tests/tracing/` |
| Kiến trúc | `transports/` không import `policy.output_guard` và không dựng `BotAction`; chỉ `gateway.list_open_slots` gán `ctx.slots` (test này chỉ bắt được việc gán lại, không bắt được sửa tại chỗ; sửa tại chỗ do OG-3/OG-6 bắt) | `tests/transports/test_no_business_rules.py` (mới) |
| Hồi quy | SF-03, confirm, cancel, booking, silence, identity, `test_confirm_attendance_qa.py`, T-12 Gateway pass nguyên trạng. Chỉ đổi câu RESCHEDULED | có sẵn |

Lưu ý giả lập lỗi (sau T-12): một lỗi "chưa rõ" đơn lẻ giờ được Gateway gửi lại và thành công. Test cần lượt bị khóa đối soát phải dùng `clinic.fail_unknown(op, WRITE_MAX_SENDS, apply_first=True)`; test cần "ghi thành công sau khi gửi lại" dùng `fail_next(..., outcome_unknown=True)`.

Xác minh: `make check` (ruff check + ruff format --check + pytest).

## 6. Rủi ro và câu hỏi mở

- **False positive làm hỏng cuộc gọi.** OG-0 rất chặt: quên đăng ký một câu mới là chuyển máy. Giảm rủi ro bằng test quét mọi nhánh Dialogue hiện có, cộng test tĩnh "mọi `BotAction(...)` trong `engine/dialogue/` dùng hằng hoặc renderer". **Cần chốt:** có cần `output_guard.mode: shadow` (chỉ trace) cho một đợt diễn tập Phone không? Đề xuất mặc định `enforce`.
- **Mã lỗi HTTP mới `CALL_START_BLOCKED`** làm thay đổi hợp đồng API. Phương án thay thế: dùng `500 INTERNAL_ERROR` sẵn có. Cần chốt.
- **Renderer phải thuần**: là ràng buộc mới cho mọi câu thoại sau này (T-10, T-11). Cần ghi vào docstring `templates.py`.
- **Metadata câu hỏi fail-closed thay vì persist** (§3.2): câu hỏi động luôn bị coi là lộ lịch khi đọc lại. Hiện mọi câu hỏi động đều lộ lịch nên không có false positive. Nếu T-10/T-11 thêm câu hỏi động không lộ lịch mà cần đọc lại trên voicemail, lúc đó mới persist `template_id` vào `Question` (tăng `SCHEMA_VERSION`).
- **Chi phí OG-6**: so sánh `ctx.slots` với snapshot mỗi lượt. Tối đa vài chục slot (`SLOT_SEARCH_MAX_WINDOWS`, `MAX_SLOTS_PRESENTED`), không đáng kể.
- **Latency**: guard và render lại là CPU thuần, không I/O; không đáng kể so với ngân sách 8 giây (S-03). T-12 đã dành tới 4 giây cho gửi lại khi ghi, nên R-01 không được thêm I/O vào đường guard (ví dụ đọc lại lịch để đối chiếu).
- **Receipt chỉ sống trong RAM của lượt**: nếu process chết sau `finish_command(SUCCEEDED)` mà trước commit, receipt mất nhưng store đã ở `CLINIC_COMMITTED`. Lượt gửi lại đi `_check_retired` → đối soát, đúng như hiện nay; R-01 không làm tệ hơn.
- **Phụ thuộc B**: T-12 đã merge (`1062041`), không còn phụ thuộc mở. R-01 dựa vào bất biến của T-12 "`SUCCEEDED` ⇒ đúng trạng thái đích"; nếu B đổi bất biến này, gate §3.5 phải quay lại kiểm status làm luật chính.

## 7. Evidence dự kiến

Mỗi dòng "Điều kiện hoàn thành" trong R-01 được ánh xạ tới code và test ở §5. Riêng "cùng một cơ chế cho HTTP và Phone" được chứng minh bằng ba test: parity, test kiến trúc và test opening của LiveKit.

## 8. Đối chiếu review Rev 1 → Rev 2

| Review | Sửa ở |
| --- | --- |
| P1-1 Lộ lịch khi không ghi ledger | §3.2 allow-list, OG-0 |
| P1-2 Slot ID thật + giờ bịa | §3.3 render lại từ source registry, OG-3 |
| P1-3 Status không khớp phải đối soát | §3.5 (status sai → `WriteOutcomeUnknown`). Rev 3: phần kiểm ở Dialogue do T-12 làm ở Gateway, xem §9 |
| P1-4 Lỗi render sau khi ghi thành công | §3.5 receipt gate chạy trước `_transfer_after_error`; test gate (a) |
| P2-5 Chặn lời mở đầu | §3.7 `CallStartBlocked`, không tạo phiên, không ghi Mock |
| P2-6 "đã đặt lịch" cho RESCHEDULED | §3.8 tách renderer, sửa câu, test tĩnh |
| P2-7 Allowlist tracing | §3.9 |

## 9. Cập nhật Rev 2 → Rev 3 (sau T-12)

Baseline đổi từ `d0f3866` sang `1062041`. Trong khoảng này chỉ T-12 (Gateway, `errors.py`, test giả lập lỗi) và bộ test QA identity/confirm đụng tới phạm vi R-01. Không có thay đổi ở `templates.py`, `orchestrator.py`, `dialogue/manager.py`, `journal.py`, `session/manager.py`, `tracing/` hay transport.

| Thay đổi ở T-12 | Ảnh hưởng tới R-01 | Sửa ở |
| --- | --- | --- |
| Gateway kiểm trạng thái đích trước `journal.succeeded`, cho cả 6 thao tác | G-4 đóng. Bỏ bước kiểm status reschedule ở Dialogue. Dòng "SUCCEEDED nhưng status sai" của gate chỉ còn là phòng thủ | §1, §2 G-4, §3.5, §4 bước 3 |
| Bàn giao: 4 chỗ kiểm status ở `dialogue/manager.py` đã thừa | R-01 nhận việc dọn | §4 bước 3 |
| Ngân sách ghi 4 s dùng chung cho mọi lệnh ghi của lượt | G-5 còn tệ hơn (`/transfer` đè kết quả còn tốn ngân sách). Guard không được thêm I/O | §2 G-5, §3.5, §6 |
| Một lỗi "chưa rõ" được gửi lại và thường thành công | Đổi cách giả lập trong test; thêm ca gate (a') và (d) | §5 |

## 10. Đối chiếu review Rev 3 → Rev 4

Đã đối chiếu với code tại `1062041`: `list_open_slots` trả `list(ctx.slots)` (`clinic_gateway.py:233-234`), `CallContext.find_slot` trả thẳng dict trong `ctx.slots`, `questions.ask` gán `ctx.question.text = utterance`, và `_present` truyền `prefix` thẳng vào `offer_slots`.

| Review | Sửa ở |
| --- | --- |
| [P1] `ctx.slots` chưa đủ tin cậy làm dữ liệu gốc | §3.3 bước 2: dữ liệu gốc là snapshot `deepcopy` (đầu lượt và sau mỗi lần `list_open_slots`), không dùng `ctx.slots`. OG-6 chặn sửa tại chỗ trước commit. Test sửa dict tại chỗ ở §5 OG-2/OG-3, OG-6 |
| [P1] Receipt đúng outcome chưa chứng minh đúng slot | §3.3 bước 4: refs của template thành công phải trùng payload/result của receipt. OG-5 mở rộng; sai thì REPLACE `DONE_SAFE`. Ca "ghi A, nói B" ở §5 |
| [P1] Đọc lại câu hỏi mất metadata disclosure | §3.2: metadata xác định lại fail-closed (câu động coi như lộ lịch), OG-1 áp lại ở lượt hiện tại; kiểm slot của câu hỏi còn trong `ctx.slot_ids`; OG-6 kiểm `ctx.question` commit đúng câu đã kiểm. Test đọc lại câu có lịch với `UNREACHABLE` ở §5 OG-1 |
| [P2] Prefix là hằng bất kỳ làm lọt lời báo thành công | §3.2: `prefix` giới hạn trong `SLOT_PREFIXES`, khai báo `str_args` trên decorator, OG-0 kiểm lại. Test từ chối prefix báo thành công ở §5 OG-0 |

## 11. Đối chiếu review Rev 4 → Rev 5

Đã đối chiếu với code tại `1062041`: `silence()` / nhắc lại / quay lại cập nhật `question.turn` và giữ `text` (`manager.py:101, 165, 169`); `_decide` cho Policy chuyển máy sau khi Dialogue đã `ask()`; `RedisSessionStore.finish_command` ghi `result=None` và purge `CLINIC_COMMITTED` khi `SUCCEEDED` (`redis_store.py:278-298`); `unreachable()` bị từ chối thì gọi `transfer()` trong cùng lượt (`manager.py:133-146`).

| Review | Sửa ở |
| --- | --- |
| [P1] OG-6 chặn nhầm luồng nhắc im lặng và chuyển máy hợp lệ | §3.2: chuẩn hóa câu hỏi theo action cuối, OG-6 tách bốn trường hợp (kết thúc / nhắc lại / hỏi mới / không đổi). Action kết thúc thì xóa câu hỏi chưa phát. Fallback khôi phục slot và chuẩn hóa lại trước khi kiểm action mới. Test không chặn nhầm ở §5 OG-6 |
| [P1] Journal không lưu được receipt trên Redis | §3.3: receipt là `JournalEntry` trong RAM của `StoreCommandJournal`, chỉ ghi sau khi store ghi `SUCCEEDED` thành công; helper `entries()`. §2: giới hạn replay ở phiên còn hoạt động. Test fakeredis ở §5 |
| [P2] Gate thiếu `FAILED`, sai giả định một lệnh / lượt | §3.5: bảng 5 hàng theo thứ tự `PENDING/UNKNOWN` → một `SUCCEEDED` → nhiều `SUCCEEDED` → chỉ `FAILED` → không lệnh. §3.9: `write_attempted` / `write_succeeded` thay cho "MULTIPLE bất thường". Test (e), (f), (g) ở §5 |
| (Phát hiện thêm khi đối chiếu) G-5 mô tả sai trên Redis | §2 G-5: thực tế không có `/transfer` đè lên mà lượt kết thúc bằng 409, mất `CONFIRMED` đã chắc chắn. Test gate (a) đổi kỳ vọng: HTTP 200 `CONFIRMED`, không có `GET` đọc lại version |

## 12. Đối chiếu review Rev 5 → Rev 6

Đã đối chiếu: `_apply` chỉ đóng phiên khi `action.ended` (`orchestrator.py:348-357`); `complete_turn` trên phiên `CLINIC_COMMITTED` ném `ValueError` khi `ended=False` (`redis_store.py:206-214`); phiên kết thúc bị purge context thành `{}`.

| Review | Sửa ở |
| --- | --- |
| [P2] Receipt đúng outcome chưa bảo đảm action kết thúc phiên | §3.5 hàng 2: giữ action chỉ khi `ended=True`, `state="ENDED"`, outcome và lý do khớp receipt, guard PASS; thiếu điều kiện nào cũng REPLACE, lý do lấy từ `command.payload` của receipt. Test gate (h) ở §5 |
| [P2] Test OG-6 kỳ vọng trái với fallback và retention | §5 OG-6: kiểm slot đã khôi phục và `ctx.question is None` **trước `_apply`**; sau commit chỉ kiểm phiên đã purge và lượt tiếp theo nhận `CallEnded`. Chỉ các ca không kết thúc mới đọc lại `ctx.question` từ store |
