"""Export the current Engine utterance catalog without synthesis or network calls.

    python scripts/tts_utterance_catalog.py --date 2026-10-08
    python scripts/tts_utterance_catalog.py --date 2026-10-08 --dry-run

Exact static texts come from the runtime registry. Variant aliases and source references
help review the catalog; source references are not proof of end-to-end reachability.
This does not replace the listening audit or the dynamic renderer branch audit.
"""

import argparse
import ast
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.variants import VARIANT_IDS
from callbot.engine.policy.utterances import RENDERERS, STATIC_UTTERANCES

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "src/callbot/engine/dialogue/templates.py"
FIXED_GROUPS = frozenset(
    {
        "GREETING_OUTBOUND",
        "GREETING_INBOUND",
        "GREETING_HANDOFF_INBOUND",
        "TRANSFER",
        "IDENTITY_FAILED_TRANSFER",
    }
)
DEFERRED_STATICS = frozenset({"ASK_NAME_DECLINED", "ASK_DOB_INVALID", "ASK_DOB_DECLINED"})
RENDERER_SCENARIOS = {
    "APPOINTMENT_SUMMARY": "Confirm",
    "ATTENDANCE_READBACK": "Confirm",
    "ATTENDANCE_REREAD": "Confirm",
    "CANCEL_READBACK": "Cancel",
    "CONFIRMED_DONE": "Confirm",
    "KEEP_APPOINTMENT": "Reschedule/Confirm",
    "OFFER_SLOTS": "Reschedule/Booking",
    "ASK_DATE_AGAIN": "Reschedule/Booking",
    "SLOT_OFFER_READBACK": "Reschedule/Booking",
    "SLOT_READBACK": "Reschedule/Booking",
    "SLOT_READBACK_DA": "Reschedule/Booking",
    "CANCELLED_DONE": "Cancel",
    "RESCHEDULED_DONE": "Reschedule",
    "BOOKED_DONE": "Booking",
    "SILENCE_REPROMPT": "No-answer",
}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scenario(template_id: str) -> str:
    if template_id.startswith("GREETING_HANDOFF") or template_id == "IDENTITY_FAILED_TRANSFER":
        return "Identity/Transfer"
    if template_id.startswith(("GREETING", "ASK_NAME", "ASK_DOB", "INTRODUCE")):
        return "Identity"
    if template_id.startswith(("SILENCE", "GOODBYE")):
        return "No-answer"
    if template_id.startswith(("HOLD", "NOT_UNDERSTOOD")):
        return "Identity/Confirm/Cancel/Transfer/Reschedule/No-answer/Booking"
    if template_id.startswith(("CANCEL", "ASK_CHANGE")):
        return "Cancel"
    if template_id.startswith("CONFIRM"):
        return "Confirm"
    if template_id.startswith(("RESCHEDULE", "ROUNDS")):
        return "Reschedule"
    if template_id.startswith(("BOOK", "ASK_INTENT")):
        return "Booking"
    if template_id == "TRANSFER":
        return "Transfer"
    if template_id.startswith(("SLOT", "NO_SLOTS", "ASK_SLOT")):
        if template_id.endswith("_BOOK"):
            return "Booking"
        if template_id.endswith("_RESCHEDULE"):
            return "Reschedule"
        return "Reschedule/Booking"
    raise ValueError(f"Chưa phân loại kịch bản: {template_id}")


def _text_symbols() -> dict[str, set[str]]:
    """Match runtime text to public constants, including dictionary values."""
    symbols: dict[str, set[str]] = defaultdict(set)
    for name, value in vars(t).items():
        if not name.isupper() or name.startswith("_") or name == "STATIC_VARIANTS":
            continue
        if isinstance(value, str):
            symbols[value].add(name)
        elif isinstance(value, dict):
            for item in value.values():
                if isinstance(item, str) and item in STATIC_UTTERANCES:
                    symbols[item].add(name)
    return symbols


def source_references() -> dict[str, list[str]]:
    """Collect references to template symbols in production Python, not tests.

    Also follow references through helpers such as greeting_back(), so a constant
    accessed through a helper is not incorrectly labelled as unreferenced.
    """
    references: dict[str, set[str]] = defaultdict(set)
    for path in sorted((ROOT / "src/callbot").rglob("*.py")):
        if path == TEMPLATE_PATH:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = {
            item.asname or item.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "callbot.engine.dialogue"
            for item in node.names
            if item.name == "templates"
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
            ):
                references[node.attr].add(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    tree = ast.parse(TEMPLATE_PATH.read_text(encoding="utf-8"))
    dependencies = {
        node.name: {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    # A finite propagation over function/symbol edges; never execute renderers here.
    changed = True
    while changed:
        changed = False
        for helper, names in dependencies.items():
            for name in names:
                before = len(references[name])
                references[name].update(references[helper])
                changed |= len(references[name]) != before
    return {name: sorted(sites) for name, sites in references.items() if sites}


def _variant_aliases() -> dict[str, list[dict[str, str]]]:
    aliases: dict[str, list[dict[str, str]]] = defaultdict(list)
    for original, choices in t.STATIC_VARIANTS.items():
        group = STATIC_UTTERANCES[original].template_id
        for variant, text in zip(VARIANT_IDS[: len(choices)], choices, strict=True):
            alias = group if variant == "v0" else f"{group}_{variant}"
            aliases[text].append({"template_id": alias, "group": group, "variant": variant})
    return aliases


def _row(**values) -> dict:
    return {
        "kind": "",
        "template_id": "",
        "aliases": [],
        "scenarios": "",
        "groups": [],
        "variants": [],
        "current_text": "",
        "character_count": None,
        "text_sha256": "",
        "prebuild_candidate": False,
        "cache_policy": "",
        "selection": "",
        "source_references": [],
        "success_outcome": "",
        "discloses": False,
        "sources": {},
        "string_domains": {},
        "review_flags": [],
        "notes": "",
        "text_review_status": "PENDING",
        "listening_status": "NOT_REVIEWED",
        **values,
    }


def build_rows() -> list[dict]:
    symbols = _text_symbols()
    references = source_references()
    variant_aliases = _variant_aliases()
    rows = []
    for text, spec in STATIC_UTTERANCES.items():
        variants = variant_aliases.get(text, [])
        aliases = sorted({spec.template_id, *(v["template_id"] for v in variants)})
        groups = sorted({v["group"] for v in variants} or {spec.template_id})
        names = set(symbols.get(text, ()))
        for group in groups:
            original = next(
                (value for value, item in STATIC_UTTERANCES.items() if item.template_id == group),
                text,
            )
            names.update(symbols.get(original, ()))
        sites = sorted({site for name in names for site in references.get(name, ())})
        deferred = spec.template_id in DEFERRED_STATICS
        if deferred and sites:
            raise ValueError(f"{spec.template_id} đã được dùng; cần review lại chính sách hoãn thu")
        fixed_variants = bool(set(groups) & FIXED_GROUPS) and bool(variants)
        flags = []
        if text.startswith("Dạ"):
            flags.append("DA_OPENING")
        if len(text) >= 300:
            flags.append("TEXT_NOT_UNDER_300")
        if fixed_variants:
            flags.append("FIXED_GROUP_HAS_VARIANTS_REVIEW_R42")
        if not sites:
            flags.append("NO_SOURCE_REFERENCE_REVIEW_USAGE")
        notes = "Có thể dựng nguyên câu sau khi chốt văn bản và nghe đạt; chưa phải asset đã duyệt."
        if fixed_variants:
            notes += " Cần chốt một mẫu cho nhóm cố định theo R-42 trước khi thu các biến thể."
        if spec.success_outcome:
            notes += " Chỉ phát sau receipt thành công; audio sẵn không bỏ qua Output Guard."
        rows.append(
            _row(
                kind="STATIC",
                template_id=spec.template_id,
                aliases=aliases,
                scenarios="; ".join(sorted({scenario(group) for group in groups})),
                groups=groups,
                variants=[f"{v['group']}:{v['variant']}" for v in variants] or ["fixed"],
                current_text=text,
                character_count=len(text),
                text_sha256=text_hash(text),
                prebuild_candidate=not deferred,
                cache_policy=(
                    "DEFERRED_UNUSED_STATIC"
                    if deferred
                    else "REVIEW_FIXED_GROUP"
                    if fixed_variants
                    else "STATIC_AFTER_REVIEW"
                ),
                selection=f"REGISTERED_{len(t.static_choices(original))}_VARIANTS"
                if variants
                else "REGISTERED_FIXED",
                source_references=sites,
                success_outcome=spec.success_outcome or "",
                review_flags=flags,
                notes=notes,
            )
        )
    for template_id, spec in RENDERERS.items():
        if template_id not in RENDERER_SCENARIOS:
            raise ValueError(f"Chưa phân loại renderer: {template_id}")
        policy = "DYNAMIC_TTS_PHASE_1"
        text = ""
        notes = "Câu phụ thuộc dữ liệu/đối số; chưa dựng sẵn nguyên câu trong giai đoạn 1."
        candidate = False
        if template_id == "CANCELLED_DONE":
            text = spec.render()
            if text not in STATIC_UTTERANCES:
                raise ValueError("CANCELLED_DONE không còn trùng câu tĩnh; cần review lại")
            policy = "REUSE_STATIC_ASSET"
            candidate = True
            notes = (
                "Trùng CANCELLED_SAFE; dùng chung audio sau duyệt, giữ guard/receipt thành công."
            )
        elif template_id == "ASK_DATE_AGAIN":
            policy = "FINITE_BRANCHES_DEFERRED"
            notes = "PAST/TODAY chứa ngày động; INVALID/TOO_BROAD có câu hữu hạn. Chưa tách chúng thành static ở bước này."
        elif template_id == "SILENCE_REPROMPT":
            policy = "COMPOSITE_REQUIRES_ENUMERATION"
            notes = "Nếu câu đang chờ tĩnh, có thể dựng nguyên câu ghép sau khi liệt kê các nhánh thực tế. Câu đang chờ động vẫn TTS; không phát SILENCE thay cả utterance."
        domains = {name: sorted(values, key=repr) for name, values in spec.str_args.items()}
        rows.append(
            _row(
                kind="RENDERER",
                template_id=template_id,
                aliases=[template_id],
                scenarios=RENDERER_SCENARIOS[template_id],
                groups=[template_id],
                variants=list(domains.get("variant", ["parameterized"])),
                current_text=text,
                character_count=len(text) if text else None,
                text_sha256=text_hash(text) if text else "",
                prebuild_candidate=candidate,
                cache_policy=policy,
                selection="PARAMETERIZED_RENDERER",
                source_references=references.get(spec.render.__name__, []),
                success_outcome=spec.success_outcome or "",
                discloses=spec.discloses,
                sources=dict(spec.sources),
                string_domains=domains,
                notes=notes,
            )
        )
    for text, names in sorted(symbols.items()):
        if text in STATIC_UTTERANCES:
            continue
        for name in sorted(names):
            rows.append(
                _row(
                    kind="COMPONENT",
                    template_id=name,
                    aliases=[name],
                    current_text=text,
                    character_count=len(text),
                    text_sha256=text_hash(text),
                    cache_policy="NOT_A_COMPLETE_UTTERANCE",
                    selection="RENDERER_COMPONENT",
                    source_references=references.get(name, []),
                    notes="Mảnh câu/hằng nội dung, chưa đăng ký là utterance trọn vẹn; không thu riêng rồi dùng thay cả câu.",
                )
            )
    return sorted(rows, key=lambda row: (row["kind"], row["template_id"]))


def validate_rows(rows: list[dict]) -> None:
    statics = [row for row in rows if row["kind"] == "STATIC"]
    if len(statics) != len(STATIC_UTTERANCES) or {row["current_text"] for row in statics} != set(
        STATIC_UTTERANCES
    ):
        raise ValueError("Catalog không phủ đúng toàn bộ nguyên văn trong registry tĩnh")
    if {row["template_id"] for row in rows if row["kind"] == "RENDERER"} != set(RENDERERS):
        raise ValueError("Catalog chưa phủ toàn bộ renderer")
    aliases = {alias for row in statics for alias in row["aliases"]}
    for row in rows:
        if row["current_text"]:
            if row["character_count"] != len(row["current_text"]) or row[
                "text_sha256"
            ] != text_hash(row["current_text"]):
                raise ValueError(f"Sai độ dài/hash: {row['template_id']}")
        if row["kind"] == "COMPONENT" and row["prebuild_candidate"]:
            raise ValueError("Không được dựng component như câu hoàn chỉnh")
    for original in t.STATIC_VARIANTS:
        group = STATIC_UTTERANCES[original].template_id
        expected = {
            group,
            *(f"{group}_{variant}" for variant in VARIANT_IDS[1 : len(t.static_choices(original))]),
        }
        if not expected <= aliases:
            raise ValueError(f"Thiếu alias biến thể của {group}")


def _revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, check=True
    )
    return result.stdout.decode("ascii").strip()


def build_catalog(export_date: str) -> dict:
    date.fromisoformat(export_date)
    rows = build_rows()
    validate_rows(rows)
    statics = [row for row in rows if row["kind"] == "STATIC"]
    previous_path = ROOT / "docs/evidence/tts-static-cache/tts-utterance-review-2026-10-07.csv"
    previous = {}
    if previous_path.exists():
        with previous_path.open(encoding="utf-8-sig", newline="") as handle:
            previous = {row["template_id"]: row["current_text"] for row in csv.DictReader(handle)}
    current = {row["template_id"]: row["current_text"] for row in statics}
    delta = {
        "previous_review": previous_path.relative_to(ROOT).as_posix(),
        "added_ids": sorted(current.keys() - previous.keys()),
        "removed_ids": sorted(previous.keys() - current.keys()),
        "changed_ids": sorted(
            key for key in current.keys() & previous.keys() if current[key] != previous[key]
        ),
    }
    return {
        "schema_version": 1,
        "export_date": export_date,
        "owner": "Hưng",
        "source_revision": _revision(),
        "template_sha256": hashlib.sha256(TEMPLATE_PATH.read_bytes()).hexdigest(),
        "counts": {
            "static_unique_texts": len(statics),
            "static_prebuild_texts": sum(row["prebuild_candidate"] for row in statics),
            "static_deferred_texts": sum(not row["prebuild_candidate"] for row in statics),
            "static_alias_ids": len({alias for row in statics for alias in row["aliases"]}),
            "static_variant_groups": len(t.STATIC_VARIANTS),
            "renderer_count": len(RENDERERS),
            "component_count": sum(row["kind"] == "COMPONENT" for row in rows),
            "static_characters": sum(row["character_count"] for row in statics),
            "static_da_openings": sum("DA_OPENING" in row["review_flags"] for row in statics),
        },
        "delta_from_previous_review": delta,
        "rows": rows,
    }


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def markdown(catalog: dict) -> str:
    counts = catalog["counts"]
    delta = catalog["delta_from_previous_review"]
    lines = [
        f"# Danh mục câu thoại hiện tại — {catalog['export_date']}",
        "",
        "**Người thực hiện: Hưng. Xuất nguyên văn Engine hiện tại; chưa gọi Vbee hoặc chấm nghe.**",
        "",
        f"Nguồn: `{catalog['source_revision']}`; hash template `{catalog['template_sha256']}`.",
        f"Có **{counts['static_unique_texts']} nguyên văn tĩnh**, **{counts['static_alias_ids']} ID/alias**, **{counts['static_variant_groups']} nhóm biến thể**, **{counts['renderer_count']} renderer** và **{counts['component_count']} mảnh nội dung**.",
        f"Câu tĩnh tổng cộng **{counts['static_characters']:,} ký tự**, **{counts['static_da_openings']} câu mở đầu bằng Dạ**. Số này tính catalog, không phải tần suất trong cuộc gọi.",
        "",
        "## Cách đọc danh mục",
        "",
        "- `STATIC_AFTER_REVIEW`: câu tĩnh có thể dựng nguyên câu sau khi chốt chữ và nghe đạt.",
        "- `REVIEW_FIXED_GROUP`: có biến thể ở nhóm PRD R-42 yêu cầu giữ cố định; cần chốt lại trước khi thu. Không coi các biến thể này đã được duyệt.",
        "- `REUSE_STATIC_ASSET`: renderer trả đúng một câu tĩnh đã có; dùng chung asset, không tốn request dựng thứ hai.",
        "- `DYNAMIC_TTS_PHASE_1`: câu chứa dữ liệu/đối số, tiếp tục TTS trong giai đoạn 1.",
        "- `FINITE_BRANCHES_DEFERRED` / `COMPOSITE_REQUIRES_ENUMERATION`: có nhánh hữu hạn nhưng chưa liệt kê thành câu cố định trong bước này.",
        "- `NOT_A_COMPLETE_UTTERANCE`: mảnh nội dung; không dùng audio mảnh thay toàn câu.",
        "",
        "Biến thể lấy từ STATIC_VARIANTS của Engine; cùng nguyên văn chỉ một dòng. Chào đầu/chuyển máy giữ một câu, nhóm hỏi đáp giữ ba câu. Tham chiếu nguồn không chứng minh mọi nhánh đều đạt được. DEFERRED_UNUSED_STATIC giữ mẫu dự phòng trong Engine nhưng chưa thu vì chưa có call site.",
        "",
        "Hash ở bước này là hash nguyên văn text, chưa phải cache key/manifest runtime. Chưa có audio hay kết quả nghe. Renderer chưa điền dữ liệu mẫu; audit đủ nhánh và các câu ghép im lặng thực tế là công việc tiếp theo của Bước A.",
        "",
        "## Thay đổi so với review 07/10",
        "",
        f"Thêm {len(delta['added_ids'])} ID: "
        + ", ".join(f"`{item}`" for item in delta["added_ids"]),
        f"Đổi nguyên văn {len(delta['changed_ids'])} ID; không còn trong snapshot hiện tại {len(delta['removed_ids'])} ID.",
        "",
        "## Toàn bộ câu tĩnh",
        "",
        "| ID / alias | Kịch bản | Biến thể | Câu hiện tại | Ký tự | Chính sách audio | Cờ review |",
        "|---|---|---|---|---:|---|---|",
    ]
    for row in catalog["rows"]:
        if row["kind"] == "STATIC":
            lines.append(
                f"| {' / '.join(row['aliases'])} | {row['scenarios']} | {'; '.join(row['variants'])} | {_escape(row['current_text'])} | {row['character_count']} | {row['cache_policy']} | {'; '.join(row['review_flags'])} |"
            )
    lines += [
        "",
        "## Renderer",
        "",
        "| ID | Kịch bản | Miền đối số chuỗi | Chính sách audio | Ghi chú |",
        "|---|---|---|---|---|",
    ]
    for row in catalog["rows"]:
        if row["kind"] == "RENDERER":
            domains = json.dumps(row["string_domains"], ensure_ascii=False, sort_keys=True)
            lines.append(
                f"| {row['template_id']} | {row['scenarios']} | {_escape(domains)} | {row['cache_policy']} | {row['notes']} |"
            )
    lines += [
        "",
        "## Mảnh nội dung không phải câu hoàn chỉnh",
        "",
        "| ID | Nội dung |",
        "|---|---|",
    ]
    for row in catalog["rows"]:
        if row["kind"] == "COMPONENT":
            lines.append(f"| {row['template_id']} | {_escape(row['current_text'])} |")
    lines += [
        "",
        "## Chạy lại",
        "",
        "```powershell",
        "$env:PYTHONUTF8 = '1'",
        f"python scripts/tts_utterance_catalog.py --date {catalog['export_date']} --dry-run",
        f"python scripts/tts_utterance_catalog.py --date {catalog['export_date']}",
        "```",
        "",
        "CSV và JSON cùng tên lưu nguyên văn, hash, metadata guard, alias, nơi tham chiếu và trạng thái review. dry-run chỉ in thống kê và kiểm coverage; cả hai lệnh đều không gọi provider.",
        "",
    ]
    return "\n".join(lines)


def write_catalog(catalog: dict, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    stem = f"tts-utterance-catalog-{catalog['export_date']}"
    paths = [out / f"{stem}.{suffix}" for suffix in ("csv", "json", "md")]
    rows = catalog["rows"]
    with paths[0].open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )
    paths[1].write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths[2].write_text(markdown(catalog), encoding="utf-8")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Ngày snapshot theo giờ Việt Nam, YYYY-MM-DD")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/evidence/tts-static-cache")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = build_catalog(args.date)
    print(json.dumps(catalog["counts"], ensure_ascii=False, indent=2))
    print(json.dumps(catalog["delta_from_previous_review"], ensure_ascii=False, indent=2))
    if not args.dry_run:
        for path in write_catalog(catalog, args.out):
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
