"""Registry câu thoại và ledger render của lượt (R-01 §3.2).

Output Guard không chấp nhận chuỗi tùy ý: câu bot nói phải là hằng tĩnh đã đăng ký (`static`), hoặc là
kết quả của một renderer đã đăng ký (`@renderer`) được ghi vào ledger của lượt. Metadata (`discloses`,
`success_outcome`) nằm trên template, không suy từ text.

Renderer lưu `refs` (mã appointment / slot đã dùng), không lưu dict dữ liệu: guard lấy lại dữ liệu gốc
từ source registry theo ref và render lại để so nguyên văn (§3.3). Vì vậy renderer phải là hàm thuần của
(dữ liệu nguồn, tham số); `ctx` chỉ dùng để assert.

Ledger gắn với lượt qua ContextVar (cùng mẫu `journal.bind_journal`). Không bind (unit test gọi template
trực tiếp) thì decorator chỉ render.
"""

import inspect
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Literal, Optional, TypeVar

from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.types import Outcome

# Mã chặn của Output Guard (ngoài SF-01..SF-05)
OUTPUT_UNREGISTERED = "OUTPUT_UNREGISTERED"
OUTPUT_UNPROVEN_SUCCESS = "OUTPUT_UNPROVEN_SUCCESS"

# Kiểu nguồn của một tham số renderer:
# APPOINTMENT: lịch đọc qua SourceRecorder trong lượt; WRITTEN: bản ghi Clinic trả về trong receipt;
# SLOT / SLOTS: slot trong snapshot GET /slots mới nhất
SourceKind = Literal["APPOINTMENT", "WRITTEN", "SLOT", "SLOTS"]
RefKind = Literal["APPOINTMENT", "SLOT"]
# Slot của câu đề xuất phải thuộc presented_slot_ids; câu đọc lại / chọn phải là selected_slot_id
SlotScope = Literal["PRESENTED", "SELECTED"]


@dataclass(frozen=True)
class UtteranceSpec:
    template_id: str
    discloses: bool = False
    success_outcome: Optional[Outcome] = None


@dataclass(frozen=True)
class RendererSpec(UtteranceSpec):
    render: Callable[..., str] = field(default=lambda: "", compare=False, repr=False)
    sources: Mapping[str, SourceKind] = field(default_factory=dict)
    str_args: Mapping[str, Collection[str]] = field(default_factory=dict)
    slot_scope: Optional[SlotScope] = None


@dataclass(frozen=True)
class SourceRef:
    param: str
    kind: RefKind
    id: Optional[str]


@dataclass(frozen=True)
class RenderRecord:
    template_id: str
    refs: tuple[SourceRef, ...]
    args: Mapping[str, Any]
    text: str


STATIC_UTTERANCES: dict[str, UtteranceSpec] = {}
RENDERERS: dict[str, RendererSpec] = {}

_ledger: ContextVar[Optional[list[RenderRecord]]] = ContextVar("utterance_ledger", default=None)


def static(template_id: str, text: str, *, success_outcome: Optional[Outcome] = None) -> str:
    """Đăng ký một câu nói trọn vẹn không chứa dữ liệu lịch; trả lại chính text."""
    existing = STATIC_UTTERANCES.get(text)
    spec = UtteranceSpec(template_id, discloses=False, success_outcome=success_outcome)
    if existing is not None and existing.success_outcome != success_outcome:
        raise ValueError(f"{template_id} trùng text với {existing.template_id} khác metadata")
    STATIC_UTTERANCES.setdefault(text, spec)
    return text


F = TypeVar("F", bound=Callable[..., str])


def renderer(
    template_id: str,
    *,
    discloses: bool,
    success_outcome: Optional[Outcome] = None,
    sources: Optional[Mapping[str, SourceKind]] = None,
    str_args: Optional[Mapping[str, Collection[str]]] = None,
    slot_scope: Optional[SlotScope] = None,
) -> Callable[[F], F]:
    """Đăng ký hàm dựng câu động. `sources`: tham số nào là dữ liệu nguồn và kiểu gì.

    `str_args`: miền giá trị của tham số chuỗi — render ngoài miền bị chặn (OG-0).
    Tham số không phải nguồn (trừ `ctx`) được lưu vào `RenderRecord.args` để guard render lại.
    """

    def decorate(function: F) -> F:
        signature = inspect.signature(function)
        spec = RendererSpec(
            template_id,
            discloses=discloses,
            success_outcome=success_outcome,
            render=function,
            sources=dict(sources or {}),
            str_args=dict(str_args or {}),
            slot_scope=slot_scope,
        )
        if template_id in RENDERERS:
            raise ValueError(f"Renderer {template_id} đã đăng ký")
        RENDERERS[template_id] = spec

        @wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            check_str_args(spec, bound.arguments)
            text = function(*bound.args, **bound.kwargs)
            ledger = _ledger.get()
            if ledger is not None:
                ledger.append(
                    RenderRecord(
                        template_id,
                        refs=source_refs(spec, bound.arguments),
                        args={
                            name: value
                            for name, value in bound.arguments.items()
                            if name != "ctx" and name not in spec.sources
                        },
                        text=text,
                    )
                )
            return text

        wrapper.spec = spec  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorate


def check_str_args(spec: RendererSpec, arguments: Mapping[str, Any]) -> None:
    for name, domain in spec.str_args.items():
        if arguments.get(name) not in domain:
            raise SevereFailureBlocked(
                OUTPUT_UNREGISTERED, f"{spec.template_id}: tham số {name} ngoài miền đăng ký"
            )


def source_refs(spec: RendererSpec, arguments: Mapping[str, Any]) -> tuple[SourceRef, ...]:
    refs: list[SourceRef] = []
    for name, kind in spec.sources.items():
        value = arguments.get(name)
        if kind in ("APPOINTMENT", "WRITTEN"):
            refs.append(SourceRef(name, "APPOINTMENT", _id(value, "appointment_id")))
        elif kind == "SLOT":
            refs.append(SourceRef(name, "SLOT", _id(value, "slot_id")))
        else:
            refs.extend(SourceRef(name, "SLOT", _id(item, "slot_id")) for item in value or [])
    return tuple(refs)


def _id(value: Any, key: str) -> Optional[str]:
    found = value.get(key) if isinstance(value, Mapping) else None
    return found if isinstance(found, str) and found else None


@contextmanager
def bind_ledger(ledger: list[RenderRecord]) -> Iterator[list[RenderRecord]]:
    token = _ledger.set(ledger)
    try:
        yield ledger
    finally:
        _ledger.reset(token)
