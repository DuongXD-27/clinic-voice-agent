"""Export the standardized Engine texts for the first static audio build, without TTS.

    python scripts/tts_utterance_catalog.py --date 2026-10-08
    python scripts/tts_static_shortlist.py --date 2026-10-08

The reduction map retains the old 125 IDs for review only. Runtime audio must match
exactly the new Engine utterance; this map must never select a substitute audio.
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/evidence/tts-static-cache"


def build_shortlist(catalog: dict) -> dict:
    mapping_path = DATA / f"tts-static-reduction-map-{catalog['export_date']}.csv"
    with mapping_path.open(encoding="utf-8-sig", newline="") as handle:
        mappings = list(csv.DictReader(handle))
    before_by_group = defaultdict(list)
    for mapping in mappings:
        before_by_group[mapping["proposed_group"]].append(mapping)
    assets = []
    by_group = defaultdict(list)
    for row in catalog["rows"]:
        if row["kind"] != "STATIC" or not row["prebuild_candidate"]:
            continue
        group = row["groups"][0]
        if group not in before_by_group:
            raise ValueError(f"Nhóm mới {group}: cần review trước khi đưa vào đợt thu")
        asset = {
            "template_id": row["template_id"],
            "group": group,
            "source_template_ids": sorted(
                mapping["current_template_id"] for mapping in before_by_group[group]
            ),
            "utterance": row["current_text"],
            "character_count": row["character_count"],
            "text_sha256": row["text_sha256"],
            "success_outcome": row["success_outcome"],
            "text_review_status": "ENGINE_STANDARDIZED_PENDING_LISTENING",
            "listening_status": "NOT_REVIEWED",
        }
        assets.append(asset)
        by_group[group].append(asset["template_id"])
    if len(assets) != catalog["counts"]["static_prebuild_texts"]:
        raise ValueError("Danh sách thu không khớp catalog")
    if len({asset["utterance"] for asset in assets}) != len(assets):
        raise ValueError("Câu trùng nguyên văn: cần gộp trước khi thu")
    for mapping in mappings:
        group = mapping["proposed_group"]
        if group and group not in by_group:
            raise ValueError(f"Nhóm {group} không còn trong Engine: cần review mapping")
        mapping["draft_candidates"] = by_group[group] if group else []
        mapping["decision"] = "ENGINE_GROUP_STANDARDIZED" if group else "DEFER_AUDIO_CHECK_USAGE"
    return {
        "export_date": catalog["export_date"],
        "template_sha256": catalog["template_sha256"],
        "baseline_static_texts": len({mapping["current_text"] for mapping in mappings}),
        "engine_static_texts": catalog["counts"]["static_unique_texts"],
        "deferred_static_texts": catalog["counts"]["static_deferred_texts"],
        "recording_static_texts": len(assets),
        "da_openings": sum(asset["utterance"].startswith("Dạ") for asset in assets),
        "characters": sum(asset["character_count"] for asset in assets),
        "assets": sorted(assets, key=lambda asset: asset["template_id"]),
        "mappings": mappings,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                    for key, value in row.items()
                }
            )


def markdown(proposal: dict) -> str:
    before, after = proposal["baseline_static_texts"], proposal["recording_static_texts"]
    lines = [
        f"# Review câu cố định đã chuẩn hoá — {proposal['export_date']}",
        "",
        f"**Người thực hiện: Hưng. Danh sách thu: {after} câu, giảm {before - after}/{before} câu ({(before - after) / before:.1%}).**",
        "",
        "Đã áp câu chữ vào template Engine. Các câu dưới đây là nguyên văn Engine hiện tại; trạng thái thu/nghe audio và cache xem plan chính cùng evidence đợt thu.",
        "",
        "Plan chính: [kế hoạch chuẩn hoá và cache](tts-static-cache-plan-2026-10-07.md). CSV/JSON đối chiếu nằm trong `docs/evidence/tts-static-cache/`.",
        "",
        f"Registry có {proposal['engine_static_texts']} câu: {after} câu trong đợt thu và {proposal['deferred_static_texts']} mẫu dự phòng chưa có call site, tạm hoãn thu. Ba nhóm dự phòng còn một mẫu mỗi nhóm, không còn bốn biến thể.",
        "",
        f"Số câu mở bằng **Dạ: 85 → {proposal['da_openings']}/{after}**; tổng text đợt thu **{proposal['characters']:,} ký tự**. Số ký tự không phải số tiền hoặc kết quả nghe.",
        "",
        "## Cách chuẩn hoá",
        "",
        "- Chào đầu outbound/inbound/handoff và chuyển máy: một nguyên văn mỗi tình huống, giữ công bố AI và câu hỏi mở khi có thể xác minh.",
        "- Hỏi đáp thông thường: ba cách nói; chọn ổn định giữa worker/replay, ưu tiên câu chưa nói trong lịch sử và tránh mở liên tiếp bằng Dạ khi có lựa chọn khác.",
        "- Gộp giới thiệu lại inbound/outbound, hỏi tên để xác minh và hỏi ngày sinh để xác minh. Các call site cũ dùng chung nhóm; không đổi điều kiện xác minh.",
        "- Giữ riêng xin thêm tên sau ngày sinh và hỏi lại tên. Câu huỷ và từng kết quả đặt/đổi/xác nhận giữ riêng, bảo toàn receipt và xác nhận huỷ hai lượt.",
        "- Bỏ lời hứa gọi lại khi chưa có scheduler. Câu hết giờ trống/giờ vừa bị đặt giữ lý do và trạng thái lịch cũ.",
        "- Renderer: cố định khung đọc lại an toàn, thêm dấu phẩy ngày giờ/cơ sở, bỏ lặp buổi trong câu đọc một slot và rút câu ghép mời hai slot. Cùng ngày đọc ngày một lần; khác ngày vẫn đọc đủ từng ngày.",
        "",
        "## Nguyên văn để thu và nghe",
        "",
        "| ID Engine | Nhóm | Utterance | Ký tự |",
        "|---|---|---|---:|",
    ]
    for asset in proposal["assets"]:
        utterance = asset["utterance"].replace("|", "\\|")
        lines.append(
            f"| {asset['template_id']} | {asset['group']} | {utterance} | {asset['character_count']} |"
        )
    lines += [
        "",
        "## Việc tiếp theo",
        "",
        "- Kiểm tiến độ thu trong plan chính và nghe duyệt audio ứng viên; câu đọc chưa tự nhiên quay lại sửa Engine rồi cập nhật hash và sinh lại riêng câu đổi.",
        "- Chưa đưa câu nào vào manifest release khi chưa nghe đạt; metadata ENGINE_STANDARDIZED_PENDING_LISTENING không phải audio đã duyệt.",
        "- 73 là các câu tĩnh đơn. Câu ghép SILENCE_REPROMPT cần liệt kê nguyên câu sẽ tăng số asset; renderer chứa ngày giờ vẫn TTS động trong giai đoạn đầu.",
        "- Mapping ID cũ giữ phục vụ review trước/sau; không dùng để chọn audio gần đúng. Các nhóm dự phòng cần kiểm luồng thực tế trước khi thu hoặc xoá.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", type=Path, default=DATA)
    parser.add_argument("--review-out", type=Path, default=ROOT / "docs/plans")
    args = parser.parse_args()
    source = DATA / f"tts-utterance-catalog-{args.date}.json"
    catalog = json.loads(source.read_text(encoding="utf-8"))
    template = ROOT / "src/callbot/engine/dialogue/templates.py"
    if hashlib.sha256(template.read_bytes()).hexdigest() != catalog["template_sha256"]:
        raise ValueError("Template đã đổi; xuất lại catalog trước khi xuất danh sách thu")
    proposal = build_shortlist(catalog)
    args.out.mkdir(parents=True, exist_ok=True)
    args.review_out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / f"tts-static-shortlist-{args.date}.csv", proposal["assets"])
    write_csv(args.out / f"tts-static-reduction-map-{args.date}.csv", proposal["mappings"])
    (args.review_out / f"tts-static-shortlist-{args.date}.md").write_text(
        markdown(proposal), encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in proposal.items() if key not in {"assets", "mappings"}},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
