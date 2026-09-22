from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import FrameClassifier, VadEvent
from speech.asr.vad.energy import EnergyFrameClassifier
from speech.asr.vad.streaming import StreamingVAD, split_frames

# WebRtcVadClassifier không export ở top-level: import webrtcvad bên trong __init__ của
# nó (lazy) đòi hỏi extra "vad-webrtc" đã cài — import trực tiếp từ
# speech.asr.vad.webrtc khi cần, để không buộc mọi consumer của package này cài
# webrtcvad-wheels chỉ để dùng EnergyFrameClassifier/StreamingVAD.

__all__ = [
    "AsyncStreamingVAD",
    "EnergyFrameClassifier",
    "FrameClassifier",
    "StreamingVAD",
    "split_frames",
    "VadEvent",
]
