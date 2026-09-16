# Evidence: <Tên task / ticket>

## Mục tiêu

<Mô tả ngắn gọn mục tiêu của task: vấn đề cần giải quyết, phạm vi và kết quả mong đợi.>

## Bằng chứng trong repo

| Acceptance criterion | Bằng chứng |
| --- | --- |
| <Tiêu chí 1> | <File/hàm/class chứng minh tiêu chí, ví dụ `src/module/file.py` định nghĩa `ClassName` với ...> |
| <Tiêu chí 2> | <Mô tả cách implement và vị trí trong code> |
| <Tiêu chí 3> | <Tên unit test xác nhận, ví dụ `test_xxx` trong `tests/.../test_file.py`> |
| <Tiêu chí 4> | <...> |

## File liên quan

- `src/<path>/<file>.py`
- `src/<path>/<file>.py`
- `tests/<path>/test_<file>.py`

## Luồng hiện tại

<Mô tả luồng dữ liệu / luồng xử lý chính, nếu có.>

```text
<input>
  -> <step_1>: <output fields>, status=<next_status>
  -> <step_2>: <output fields>, status=<next_status>
  -> <step_3>: <output fields>, status=<final_status>
```

## Quy trình xác minh

Cài môi trường (một lần): `make install` (tương đương `pip install -e ".[dev,speech]"`).

```powershell
make check
```

`make check` chạy lần lượt (giống bước test trên CI):

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
```

Chỉ chạy test của phần liên quan: `python -m pytest tests\<test_dir> -q`

## Kết quả xác minh cục bộ (YYYY-MM-DD)

| Command | Kết quả |
| --- | --- |
| `python -m ruff check src tests` | Pass / Fail |
| `python -m ruff format --check src tests` | Pass / Fail |
| `python -m pytest -q` | Pass / Fail (<số test passed>) |
| `make check` | Pass / Fail |

## Ghi chú

- <Giới hạn phạm vi hiện tại, ví dụ: node đang là mock theo scope Sprint N.>
- <Việc sẽ làm tiếp / phụ thuộc vào task khác.>
- <Rủi ro hoặc điểm cần reviewer lưu ý.>
