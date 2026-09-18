"""Lỗi TTS có tên — tầng ngoài `speech/tts/` chỉ bắt `TTSError`, không thấy ngoại lệ của thư viện mạng."""


class TTSError(Exception):
    """Gốc của mọi lỗi TTS. `code` là mã ngắn để trace/log, không chứa text đã gửi."""

    def __init__(self, message: str, code: str = "tts_error") -> None:
        super().__init__(message)
        self.code = code


class TTSUnavailable(TTSError):
    """Tạm thời không sinh được audio: timeout, lỗi mạng, provider quá tải (429/5xx), WS đóng bất thường."""


class TTSRejected(TTSError):
    """Provider từ chối yêu cầu: key sai, hết quota, gói không đủ, voice/model/text không hợp lệ."""
