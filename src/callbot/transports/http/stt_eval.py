"""API cho PM tự kiểm tra chất lượng STT trên file WAV — không mở cuộc gọi, không ghi trace.

- `/v1/stt/turn`: file là một lượt nói (như audio_url của /v1/calls/{id}/turn).
- `/v1/stt/transcribe`: file dài nhiều câu, cắt đoạn bằng VAD.

Chỉ mount khi STT_EVAL_ENABLED=true (main.py), luôn sau bearer key. Không ghi trace: lượt test
sẽ trộn vào số liệu STT production trên dashboard observability. Logic nằm ở
`speech.asr.offline`; module này chỉ nhận audio (URL/upload) và đổi kiểu dữ liệu.
"""

import ipaddress
import logging
import socket
from time import perf_counter_ns
from typing import Annotated, Callable, Literal, Optional, TypeVar

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from speech.asr import Recognizer
from speech.asr.offline import (
    AudioTooLong,
    ComparisonResult,
    InvalidAudio,
    OfflineTranscription,
    SourceReport,
    TurnTranscription,
    transcribe_offline,
    transcribe_turn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/stt", tags=["stt-eval"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024
_MAX_REDIRECTS = 3
_FETCH_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
# Test thay bằng httpx.MockTransport / resolver giả; None = mạng thật
_transport: Optional[httpx.BaseTransport] = None
_resolve = socket.getaddrinfo

T = TypeVar("T")
Source = Literal["url", "upload"]
SttTurnWarning = Literal["NARROWBAND_SOURCE", "CLIPPING", "LOW_LEVEL"]
SttWarning = Literal["NARROWBAND_SOURCE", "CLIPPING", "LOW_LEVEL", "LOW_SNR", "NO_SPEECH_DETECTED"]
SttTurnStep = Literal["DOWNMIX_MONO", "TELEPHONE_BAND", "DC_REMOVAL", "RESAMPLE", "GAIN_NORMALIZE"]
SttStep = Literal[
    "DOWNMIX_MONO", "TELEPHONE_BAND", "DC_REMOVAL", "RESAMPLE", "GAIN_NORMALIZE", "VAD_SEGMENT"
]

_AUDIO_URL_HELP = (
    "URL http(s) public tới file WAV. Không nhận địa chỉ nội bộ/localhost — file trên máy thì "
    "dùng route `/upload`."
)
_TELEPHONE_HELP = (
    "Hạ file về 8 kHz trước (giống đường điện thoại production). Bật khi muốn biết chất lượng "
    "lúc gọi thật; tắt để đo chất lượng tốt nhất model đạt được trên file gốc."
)
_PRODUCTION_HELP = (
    "Chạy thêm bản `production`: y hệt POST /v1/calls/{call_id}/turn (hạ 8 kHz, không tiền xử lý) "
    "— để thấy bot đang nghe ra gì với clip này."
)
_COMPARE_HELP = (
    "Chạy thêm bản `raw`: nguyên file, không tiền xử lý, không cắt theo VAD (file dài hơn 30 s "
    "được chia khúc tại chỗ yên nhất) — để so với kết quả chính."
)
_CONFIDENCE_DOC = """
`confidence` là xác suất trung bình model gán cho các token nó chọn — **cao không có nghĩa là
đúng** (model có thể nghe nhầm rất tự tin), chủ yếu giúp nhận ra chữ bịa do nhiễu/lặng.
`null` khi provider không trả confidence.
"""
_TURN_DOC = (
    """
File là **một lượt nói** (tối đa 30 s), decode nguyên clip một lần — không cắt đoạn. Chi tiết:
`docs/reference/stt-eval-api.md`.

1. Decode WAV (PCM 8/16/24/32-bit, float, A-law, μ-law), trộn về mono.
2. Bỏ DC offset, resample **một lần** thẳng về tần số model (16 kHz) bằng soxr.
3. Khuếch đại tĩnh nếu giọng dưới −35 dBFS (tối đa +20 dB, không để peak vượt −1 dBFS).
4. Model decode nguyên clip.
"""
    + _CONFIDENCE_DOC
)
_PIPELINE_DOC = (
    """
File **dài nhiều câu** (tối đa 5 phút). Chi tiết: `docs/reference/stt-eval-api.md`.

1. Decode WAV (PCM 8/16/24/32-bit, float, A-law, μ-law), trộn về mono.
2. Bỏ DC offset, resample **một lần** thẳng về tần số model (16 kHz) bằng soxr.
3. Khuếch đại tĩnh file quá nhỏ (tối đa +20 dB, không để peak vượt −1 dBFS).
4. Silero VAD tìm các đoạn có giọng; mỗi đoạn decode riêng, text ghép theo thời gian.
   Đoạn dài hơn 30 s được chia tại chỗ yên nhất (bộ nhớ model tăng theo bình phương độ dài).
"""
    + _CONFIDENCE_DOC
)
_RTF_HELP = "latency_ms.asr / thời lượng audio; 0.05 = decode nhanh gấp 20 lần thời gian thực"


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class SttTurnRequest(BaseModel):
    audio_url: str = Field(
        max_length=2048,
        description=_AUDIO_URL_HELP + " Tối đa 25 MiB, 30 giây.",
        examples=["https://example.com/clips/huy-lich.wav"],
    )
    compare: bool = Field(default=False, description=_PRODUCTION_HELP)
    telephone_band: bool = Field(default=False, description=_TELEPHONE_HELP)


class SttTranscribeRequest(BaseModel):
    audio_url: str = Field(
        max_length=2048,
        description=_AUDIO_URL_HELP + " Tối đa 25 MiB, 5 phút.",
        examples=["https://example.com/clips/cuoc-goi.wav"],
    )
    compare: bool = Field(default=False, description=_COMPARE_HELP)
    telephone_band: bool = Field(default=False, description=_TELEPHONE_HELP)


class SttComparison(BaseModel):
    text: str
    confidence: Optional[float]
    asr_ms: float = Field(description="Thời gian model decode")


class SttModelInfo(BaseModel):
    provider: str
    model: Optional[str]
    input_sample_rate: int


class SttTurnAudioInfo(BaseModel):
    source: Source
    size_bytes: int
    format: str = Field(description="Định dạng gốc, vd PCM_16, PCM_24, FLOAT_32, ALAW, MULAW")
    sample_rate: int = Field(description="Tần số gốc của file (Hz)")
    channels: int
    duration_ms: int
    peak_dbfs: Optional[float] = Field(description="Đỉnh tín hiệu, 0 = kịch trần")
    speech_rms_dbfs: Optional[float] = Field(
        description="Độ lớn trung bình vùng có giọng; dưới −35 dBFS là file thu quá nhỏ"
    )
    clipping_ratio: float = Field(description="Tỷ lệ mẫu bị kịch trần (méo, không sửa được)")


class SttAudioInfo(SttTurnAudioInfo):
    snr_db: Optional[float] = Field(
        description="Giọng so với nhiễu nền (theo VAD); dưới 10 dB là nhiễu nhiều. "
        "null khi không đo được (không có lặng, hoặc nền im tuyệt đối)"
    )
    speech_ms: int = Field(description="Tổng thời gian VAD coi là có giọng")


class SttTurnPreprocessing(BaseModel):
    steps: list[SttTurnStep] = Field(description="Các bước đã thực sự áp dụng, theo thứ tự")
    gain_db: float = Field(description="Gain đã cộng thêm (0 = giữ nguyên độ lớn)")
    telephone_band: bool


class SttPreprocessing(BaseModel):
    steps: list[SttStep] = Field(description="Các bước đã thực sự áp dụng, theo thứ tự")
    gain_db: float = Field(description="Gain đã cộng thêm (0 = giữ nguyên độ lớn)")
    telephone_band: bool


class SttTurnLatency(BaseModel):
    download: Optional[float] = Field(description="Tải audio_url; null khi upload")
    decode: float
    preprocess: float
    asr: float = Field(description="Thời gian model decode clip (không gồm bản production)")
    total: float = Field(
        description="Toàn bộ request phía server, gồm cả tải file và bản production"
    )


class SttLatency(BaseModel):
    download: Optional[float] = Field(description="Tải audio_url; null khi upload")
    decode: float
    preprocess: float
    vad: float
    asr: float = Field(description="Tổng thời gian model decode các đoạn (không gồm bản raw)")
    total: float = Field(description="Toàn bộ request phía server, gồm cả tải file và bản raw")


class SttTurnResponse(BaseModel):
    text: str = Field(description="Transcript của lượt nói")
    confidence: Optional[float] = Field(description="0–1; null nếu rỗng hoặc provider không có")
    is_silence: bool
    production: Optional[SttComparison] = Field(
        description="Chỉ có khi compare=true: kết quả y hệt POST /v1/calls/{call_id}/turn"
    )
    model: SttModelInfo
    audio: SttTurnAudioInfo
    preprocessing: SttTurnPreprocessing
    latency_ms: SttTurnLatency
    real_time_factor: Optional[float] = Field(description=_RTF_HELP)
    warnings: list[SttTurnWarning] = Field(
        description="NARROWBAND_SOURCE: file gốc ≤ 8 kHz. CLIPPING: >0,1% mẫu kịch trần. "
        "LOW_LEVEL: file thu quá nhỏ"
    )


class SttSegment(BaseModel):
    start_ms: int = Field(description="Vị trí bắt đầu đoạn trong file gốc (đã gồm phần đệm)")
    end_ms: int
    text: str
    confidence: Optional[float] = Field(description="0–1, null nếu provider không cung cấp")


class SttTranscribeResponse(BaseModel):
    text: str = Field(description="Transcript đầy đủ từ đầu đến cuối file")
    confidence: Optional[float] = Field(
        description="Trung bình confidence các đoạn, trọng số theo số từ; null nếu không có"
    )
    is_silence: bool
    segments: list[SttSegment]
    raw: Optional[SttComparison] = Field(
        description="Chỉ có khi compare=true: nguyên file, không tiền xử lý (chia khúc ≤ 30 s)"
    )
    model: SttModelInfo
    audio: SttAudioInfo
    preprocessing: SttPreprocessing
    latency_ms: SttLatency
    real_time_factor: Optional[float] = Field(description=_RTF_HELP)
    warnings: list[SttWarning] = Field(
        description="NARROWBAND_SOURCE: file gốc ≤ 8 kHz. CLIPPING: >0,1% mẫu kịch trần. "
        "LOW_LEVEL: file thu quá nhỏ. LOW_SNR: nhiễu nền lớn. NO_SPEECH_DETECTED: VAD không thấy giọng"
    )


def _check_url_allowed(url: str) -> None:
    """Chặn SSRF: chỉ http(s) tới địa chỉ public. Còn khe DNS rebinding (httpx phân giải lại) —
    chấp nhận được vì route chỉ mount khi bật cờ và luôn có bearer key."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise _error(422, "URL_NOT_ALLOWED", "audio_url không hợp lệ") from exc
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise _error(422, "URL_NOT_ALLOWED", "audio_url phải là http(s)")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = _resolve(parsed.host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise _error(502, "AUDIO_URL_FETCH_FAILED", "Không phân giải được tên miền") from exc
    for *_, sockaddr in addresses:
        address = ipaddress.ip_address(str(sockaddr[0]).split("%")[0])
        if not address.is_global or address.is_multicast:
            raise _error(422, "URL_NOT_ALLOWED", "audio_url trỏ tới địa chỉ nội bộ")


def _read_limited(response: httpx.Response) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise _error(413, "AUDIO_TOO_LARGE", "File vượt quá 25 MiB")
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > MAX_AUDIO_BYTES:
            raise _error(413, "AUDIO_TOO_LARGE", "File vượt quá 25 MiB")
    return bytes(body)


def _fetch_audio(url: str) -> bytes:
    """Redirect tự đi từng bước để kiểm tra lại địa chỉ ở mỗi hop."""
    with httpx.Client(timeout=_FETCH_TIMEOUT, transport=_transport) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            _check_url_allowed(url)
            try:
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    if response.status_code >= 400:
                        raise _error(
                            502,
                            "AUDIO_URL_FETCH_FAILED",
                            f"audio_url trả HTTP {response.status_code}",
                        )
                    return _read_limited(response)
            except httpx.TimeoutException as exc:
                raise _error(504, "AUDIO_URL_TIMEOUT", "Tải audio_url quá thời gian") from exc
            except httpx.HTTPError as exc:
                logger.warning("STT_EVAL_FETCH_FAILED:%s", type(exc).__name__)
                raise _error(502, "AUDIO_URL_FETCH_FAILED", "Không tải được audio_url") from exc
    raise _error(502, "AUDIO_URL_FETCH_FAILED", "audio_url redirect quá nhiều lần")


def _ms_since(start_ns: int) -> float:
    return (perf_counter_ns() - start_ns) / 1_000_000


def _download(url: str) -> tuple[bytes, float]:
    started = perf_counter_ns()
    data = _fetch_audio(url)
    if not data:
        raise _error(422, "EMPTY_AUDIO", "audio_url trả về nội dung rỗng")
    return data, _ms_since(started)


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise _error(413, "AUDIO_TOO_LARGE", "File vượt quá 25 MiB")
    if not data:
        raise _error(422, "EMPTY_AUDIO", "File upload rỗng")
    return data


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except AudioTooLong as exc:
        raise _error(422, "AUDIO_TOO_LONG", f"Audio dài quá {exc.limit_ms // 1000} giây") from exc
    except InvalidAudio as exc:
        raise _error(
            422,
            "INVALID_WAV",
            "Không đọc được WAV (hỗ trợ PCM 8/16/24/32-bit, float 32/64-bit, A-law, μ-law)",
        ) from exc
    except Exception as exc:
        # Chỉ ghi tên lớp: nội dung exception có thể chứa phản hồi của provider
        logger.error("STT_EVAL_FAILED:%s", type(exc).__name__)
        raise _error(500, "STT_FAILED", "Lỗi khi chạy STT") from exc


def _model_info(recognizer: Recognizer) -> SttModelInfo:
    return SttModelInfo(
        provider=recognizer.name,
        model=getattr(recognizer, "model", None),
        input_sample_rate=recognizer.input_sample_rate,
    )


def _audio_fields(audio: SourceReport, source: Source, size_bytes: int) -> dict[str, object]:
    return {
        "source": source,
        "size_bytes": size_bytes,
        "format": audio.format,
        "sample_rate": audio.sample_rate,
        "channels": audio.channels,
        "duration_ms": audio.duration_ms,
        "peak_dbfs": audio.peak_dbfs,
        "speech_rms_dbfs": audio.speech_rms_dbfs,
        "clipping_ratio": audio.clipping_ratio,
    }


def _comparison(result: Optional[ComparisonResult]) -> Optional[SttComparison]:
    if result is None:
        return None
    return SttComparison(text=result.text, confidence=result.confidence, asr_ms=result.asr_ms)


def _turn(
    request: Request,
    data: bytes,
    *,
    source: Source,
    download_ms: Optional[float],
    started: int,
    compare: bool,
    telephone_band: bool,
) -> SttTurnResponse:
    recognizer: Recognizer = request.app.state.speech.asr
    result: TurnTranscription = _run(
        lambda: transcribe_turn(
            data, recognizer=recognizer, telephone_band=telephone_band, compare=compare
        )
    )
    return SttTurnResponse(
        text=result.text,
        confidence=result.confidence,
        is_silence=not result.text,
        production=_comparison(result.production),
        model=_model_info(recognizer),
        audio=SttTurnAudioInfo(**_audio_fields(result.audio, source, len(data))),
        preprocessing=SttTurnPreprocessing(
            steps=result.steps, gain_db=result.gain_db, telephone_band=result.telephone_band
        ),
        latency_ms=SttTurnLatency(
            download=download_ms,
            decode=result.timings.decode_ms,
            preprocess=result.timings.preprocess_ms,
            asr=result.timings.asr_ms,
            total=_ms_since(started),
        ),
        real_time_factor=result.real_time_factor,
        warnings=result.warnings,
    )


def _transcribe(
    request: Request,
    data: bytes,
    *,
    source: Source,
    download_ms: Optional[float],
    started: int,
    compare: bool,
    telephone_band: bool,
) -> SttTranscribeResponse:
    recognizer: Recognizer = request.app.state.speech.asr
    result: OfflineTranscription = _run(
        lambda: transcribe_offline(
            data,
            recognizer=recognizer,
            vad_factory=request.app.state.stt_vad_factory,
            telephone_band=telephone_band,
            compare=compare,
        )
    )
    return SttTranscribeResponse(
        text=result.text,
        confidence=result.confidence,
        is_silence=not result.text,
        segments=[
            SttSegment(start_ms=s.start_ms, end_ms=s.end_ms, text=s.text, confidence=s.confidence)
            for s in result.segments
        ],
        raw=_comparison(result.raw),
        model=_model_info(recognizer),
        audio=SttAudioInfo(
            **_audio_fields(result.audio, source, len(data)),
            snr_db=result.snr_db,
            speech_ms=result.speech_ms,
        ),
        preprocessing=SttPreprocessing(
            steps=result.steps, gain_db=result.gain_db, telephone_band=result.telephone_band
        ),
        latency_ms=SttLatency(
            download=download_ms,
            decode=result.timings.decode_ms,
            preprocess=result.timings.preprocess_ms,
            vad=result.timings.vad_ms,
            asr=result.timings.asr_ms,
            total=_ms_since(started),
        ),
        real_time_factor=result.real_time_factor,
        warnings=result.warnings,
    )


@router.post(
    "/turn",
    response_model=SttTurnResponse,
    summary="STT một lượt nói (WAV qua URL)",
    description="Tải WAV từ `audio_url` rồi chạy STT cho một lượt nói.\n" + _TURN_DOC,
)
def turn_url(payload: SttTurnRequest, request: Request) -> SttTurnResponse:
    started = perf_counter_ns()
    data, download_ms = _download(payload.audio_url)
    return _turn(
        request,
        data,
        source="url",
        download_ms=download_ms,
        started=started,
        compare=payload.compare,
        telephone_band=payload.telephone_band,
    )


@router.post(
    "/turn/upload",
    response_model=SttTurnResponse,
    summary="STT một lượt nói (WAV upload từ máy)",
    description="Upload WAV (multipart, field `file`, tối đa 25 MiB) rồi chạy STT cho một lượt "
    "nói.\n" + _TURN_DOC,
)
def turn_upload(
    request: Request,
    file: Annotated[UploadFile, File(description="File WAV của một lượt nói")],
    compare: Annotated[bool, Form(description=_PRODUCTION_HELP)] = False,
    telephone_band: Annotated[bool, Form(description=_TELEPHONE_HELP)] = False,
) -> SttTurnResponse:
    started = perf_counter_ns()
    return _turn(
        request,
        _read_upload(file),
        source="upload",
        download_ms=None,
        started=started,
        compare=compare,
        telephone_band=telephone_band,
    )


@router.post(
    "/transcribe",
    response_model=SttTranscribeResponse,
    summary="STT file dài nhiều câu (WAV qua URL)",
    description="Tải WAV từ `audio_url` rồi chạy STT với tiền xử lý và cắt đoạn.\n" + _PIPELINE_DOC,
)
def transcribe_url(payload: SttTranscribeRequest, request: Request) -> SttTranscribeResponse:
    started = perf_counter_ns()
    data, download_ms = _download(payload.audio_url)
    return _transcribe(
        request,
        data,
        source="url",
        download_ms=download_ms,
        started=started,
        compare=payload.compare,
        telephone_band=payload.telephone_band,
    )


@router.post(
    "/transcribe/upload",
    response_model=SttTranscribeResponse,
    summary="STT file dài nhiều câu (WAV upload từ máy)",
    description="Upload WAV (multipart, field `file`, tối đa 25 MiB) rồi chạy STT với tiền xử lý "
    "và cắt đoạn.\n" + _PIPELINE_DOC,
)
def transcribe_upload(
    request: Request,
    file: Annotated[UploadFile, File(description="File WAV")],
    compare: Annotated[bool, Form(description=_COMPARE_HELP)] = False,
    telephone_band: Annotated[bool, Form(description=_TELEPHONE_HELP)] = False,
) -> SttTranscribeResponse:
    started = perf_counter_ns()
    return _transcribe(
        request,
        _read_upload(file),
        source="upload",
        download_ms=None,
        started=started,
        compare=compare,
        telephone_band=telephone_band,
    )
