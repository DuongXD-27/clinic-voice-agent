"""Một bộ phân loại tiếng nói dùng chung cho cả cuộc gọi — mỗi frame phân loại đúng MỘT lần.

Trước đây mỗi consumer (VAD chính, bộ chốt câu của ASR, Speech Admission — đã gỡ 28/09 —,
evidence của Validator) có một bản Silero riêng chạy trên cùng frame: tới 4 lần suy luận/frame
và 4 quyết định có thể lệch nhau. Bug 26/09 (câu kẹt lại trong ASR) sinh ra đúng từ việc
Admission và bộ chốt câu của ASR lệch nhau 1 frame.

`STTPipeline._fanout` gọi `classify(frame)` theo đúng thứ tự thời gian thực cho MỌI frame (bộ
phân loại Silero có trạng thái — phải thấy luồng liên tục, không được thấy frame đảo thứ tự hay
chỉ một phần luồng như ASR khi bot đang nói). Consumer nhận `view()`: `is_speech(frame)` trả kết
quả đã tính cho chính đối tượng frame đó (kể cả frame phát lại từ pre-roll), không suy luận lại.

Khoá theo danh tính đối tượng (`id` + giữ tham chiếu), không theo nội dung: hai frame im lặng
giống hệt byte vẫn là hai thời điểm khác nhau.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from speech.asr.vad.base import FrameClassifier

logger = logging.getLogger(__name__)

# ~61 s ở 30 ms/frame: lớn hơn trần hàng đợi ASR (20 x 50 frame) + pre-roll, nên frame nằm chờ
# trong hàng đợi ASR vẫn còn kết quả khi ASR xử lý tới.
_DEFAULT_CAPACITY = 2048


class SharedSpeechDetector:
    def __init__(self, classifier: FrameClassifier, *, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._classifier = classifier
        self._capacity = capacity
        self._results: OrderedDict[int, tuple[bytes, bool]] = OrderedDict()
        self._missed = 0

    def classify(self, frame: bytes) -> bool:
        """Gọi đúng một lần cho mỗi frame, theo thứ tự tới."""
        is_speech = self._classifier.is_speech(frame)
        key = id(frame)
        self._results.pop(key, None)
        self._results[key] = (frame, is_speech)
        while len(self._results) > self._capacity:
            self._results.popitem(last=False)
        return is_speech

    def lookup(self, frame: bytes) -> bool:
        cached = self._results.get(id(frame))
        if cached is not None and cached[0] is frame:
            return cached[1]
        # Frame chưa qua classify() (hoặc đã quá cũ): không được đưa vào bộ phân loại có trạng
        # thái lệch thứ tự — coi là không có tiếng nói.
        self._missed += 1
        if self._missed == 1:
            logger.warning("shared_detector: frame chưa được phân loại, coi là im lặng")
        return False

    def view(self) -> FrameClassifier:
        return _DetectorView(self)


class _DetectorView:
    def __init__(self, detector: SharedSpeechDetector) -> None:
        self._detector = detector

    def is_speech(self, frame: bytes) -> bool:
        return self._detector.lookup(frame)
