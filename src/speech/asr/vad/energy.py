class EnergyFrameClassifier:
    """VAD theo năng lượng RMS — baseline để chạy khung.

    Ngưỡng cần hiệu chỉnh lại trên audio 8 kHz thật: nhiễu đường dây và codec G.711
    nâng nền nhiễu so với ghi âm sạch.
    TODO: thay bằng webrtcvad (hỗ trợ 8 kHz) / Silero VAD, hoặc end-of-turn của STT streaming.
    """

    def __init__(self, rms_threshold: float = 500.0) -> None:
        self._threshold = rms_threshold

    def is_speech(self, frame: bytes) -> bool:
        import numpy as np

        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return False
        return float(np.sqrt(np.mean(samples**2))) >= self._threshold
