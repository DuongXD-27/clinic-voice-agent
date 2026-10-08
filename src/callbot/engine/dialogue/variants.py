"""Chọn cách nói trước khi render; cùng cuộc gọi và lượt luôn cho cùng kết quả.

Không dùng RNG hay Python hash() (đổi giữa các worker). Lượt tiếp theo xoay sang biến thể
khác của cùng nhóm. Nhắc lại không gọi selector: dùng nguyên ctx.question.text đã lưu.
"""

from hashlib import blake2s

from callbot.engine.session.context import CallContext

VARIANT_IDS = ("v0", "v1", "v2", "v3")


def choose_variant(ctx: CallContext, group: str, *, variants: tuple[str, ...] = VARIANT_IDS) -> str:
    if not variants or len(set(variants)) != len(variants) or not set(variants) <= set(VARIANT_IDS):
        raise ValueError("Tập biến thể phải không rỗng, không trùng và thuộc VARIANT_IDS")
    key = f"{ctx.call_id}\0{group}".encode("utf-8")
    offset = int.from_bytes(blake2s(key, digest_size=4).digest(), "big")
    return variants[(offset + ctx.turn) % len(variants)]
