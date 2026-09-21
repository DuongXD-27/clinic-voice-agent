"""Tín hiệu dùng chung cho hai trường danh tính — tên và ngày sinh (thiết kế v1.1 §5.1, §5.2).

Tầng luật phải nói rõ *vì sao* nó không ra giá trị. "Chưa hiểu" và "đã hiểu rồi từ chối" dẫn
tới hai hành vi khác nhau: chỉ "chưa hiểu" (`Reason.NO_SIGNAL`) mới được hỏi tuyến sau. Nếu
NER được phép trả lời cả những câu đã bị luật xác định, một câu "không phải Nguyễn Văn A"
có thể quay lại thành "Nguyễn Văn A" và đi thẳng vào Verifier — đúng thứ mà tầng luật vừa chặn.

Các cụm ở đây đi chung cho cả hai trường, nhưng *phạm vi* thì không: lời sửa tên không được
làm mất ngày sinh trong cùng một lượt, và ngược lại. Bên gọi tự cắt vùng của mình rồi mới
tìm cụm trong vùng đó.

So khớp ở chế độ `mixed`: ASR hay bỏ dấu một phần ("Dạ toi la Nguyen Van A"), nên mỗi cụm
được thử cả hai dạng. Cụm bắt đầu bằng "à" bị loại khỏi dạng không dấu vì "a" là một tên
thật ("Nguyễn Văn A"), không phải lời tự sửa.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Optional, TypeVar

from callbot.engine.extraction.schema import Field
from callbot.engine.extraction.text import compile_phrases

T = TypeVar("T")


class Reason(str, Enum):
    """Vì sao tầng luật nhận hoặc không nhận giá trị. Chỉ `NO_SIGNAL` mở đường cho tuyến sau."""

    OK = "OK"
    NO_SIGNAL = "NO_SIGNAL"  # không luật nào khớp — tuyến sau được phép thử
    NEGATED = "NEGATED"  # người gọi bác bỏ chính thông tin vừa nói
    UNCERTAIN = "UNCERTAIN"  # người gọi còn phân vân — hỏi lại, không đưa vào Verifier
    AMBIGUOUS = "AMBIGUOUS"  # nhiều cách hiểu cùng hợp lệ — không chọn hộ
    OTHER_PERSON = "OTHER_PERSON"  # thông tin của người khác, không phải người gọi
    NOT_A_NAME = "NOT_A_NAME"  # câu nghiệp vụ hoặc lời đệm, không phải câu khai tên
    OUT_OF_RANGE = "OUT_OF_RANGE"  # có cấu trúc ngày nhưng giá trị không dùng được


@dataclass(frozen=True)
class Reading(Generic[T]):
    """Kết quả phân tích nội bộ: giá trị, lý do, và vùng transcript đã sinh ra nó.

    `zone` là đoạn *có thật* trong `clean(transcript)` — dùng để tách câu gộp tên + ngày sinh
    và để kiểm tra tên do NER trả về có nằm trong vùng được phép hay không. `None` nghĩa là
    không khoanh được vùng nào, nên không ai được cắt câu dựa vào kết quả này.
    """

    field: Field[T]
    reason: Reason
    zone: Optional[str] = None


# "không phải A": bác bỏ A và KHÔNG kèm giá trị thay thế, trừ khi có "mà là B" đi sau.
NEGATIONS = compile_phrases(["không phải", "đâu phải", "chả phải", "chẳng phải"])
# "A, à nhầm B": tự sửa — bản thân cụm đã hàm ý giá trị đúng nằm ngay sau nó.
CORRECTIONS = compile_phrases(
    [
        "à không",
        "à nhầm",
        "nhầm",
        "nhầm rồi",
        "à quên",
        "xin lỗi",
        "ý là",
        "ý tôi là",
        "ý em là",
        "sửa lại",
        "nói lại",
        "à thôi",
        "à mà không",
    ],
    unaccented_exclude=["à không", "à nhầm", "à quên", "à thôi", "à mà không"],
)
# Phần khẳng định sau một lời phủ định: "không phải A *mà là* B".
AFFIRMATIONS = compile_phrases(["mà là", "mà phải là", "mới đúng là", "phải là", "mà"])
# Người gọi tự báo là mình không chắc. Không dùng riêng "chắc": "Chắc" nằm được trong tên.
UNCERTAINTY = compile_phrases(
    [
        "hình như",
        "hình như là",
        "có lẽ",
        "chắc là",
        "chắc tên",
        "không chắc",
        "không nhớ rõ",
        "không nhớ lắm",
        "không nhớ chính xác",
        "không rõ lắm",
        "thì phải",
    ]
)
# "A hay B", "A hoặc B": hai giá trị cùng được nêu, không có tín hiệu nào là lời sửa.
ALTERNATIVES = compile_phrases(["hay là", "hay", "hoặc là", "hoặc"])


def token_index(tokens: list[str], offset: int) -> int:
    """Token chứa ký tự thứ `offset` của `" ".join(tokens)`.

    Cho phép tìm cụm bằng regex trên chuỗi rồi quay về chỉ số token, thay vì viết một bộ
    so khớp riêng theo token.
    """
    at = 0
    for index, token in enumerate(tokens):
        at += len(token)
        if offset < at:
            return index
        at += 1
    return max(len(tokens) - 1, 0)
