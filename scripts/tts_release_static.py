"""Package validated audio after explicit listening approval; never calls TTS.

Approval may be recorded directly from the owner's confirmation, without an HTML
or listening CSV workflow. Existing release directories are never overwritten.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from inference.tts.config import VbeeTTSConfig
from inference.tts.static_identity import SCHEMA_VERSION, canonical_json, digest

if __package__:
    from scripts.tts_build_static import (
        ROOT,
        atomic_write,
        audio_config,
        build_lock,
        load_shortlist,
        plan_build,
        wav_metadata,
    )
else:
    from tts_build_static import (
        ROOT,
        atomic_write,
        audio_config,
        build_lock,
        load_shortlist,
        plan_build,
        wav_metadata,
    )


def release_candidate(
    candidate: Path,
    output: Path,
    assets: list[dict],
    catalog: dict,
    identity: dict,
    *,
    reviewer: str,
    approval_note: str,
) -> dict:
    if not reviewer.strip() or not approval_note.strip():
        raise ValueError("Cần ghi người duyệt và xác nhận đã nghe đạt")
    if output.exists():
        raise ValueError("Kho release đã tồn tại; chọn phiên bản mới, không ghi đè")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    try:
        with build_lock(candidate):
            original = json.loads((candidate / "build_manifest.json").read_text(encoding="utf-8"))
            entries = plan_build(assets, identity, candidate)
            if (
                original["template_sha256"] != catalog["template_sha256"]
                or original["audio_config"] != identity
                or any(e["build_status"] != "GENERATED" for e in entries)
            ):
                raise ValueError("Audio ứng viên thiếu, hỏng hoặc khác Engine/cấu hình hiện tại")
            approved_at = datetime.now(timezone.utc).isoformat()
            approval = {
                "method": "owner_confirmation",
                "reviewer": reviewer.strip(),
                "approved_at": approved_at,
                "statement": approval_note.strip(),
            }
            stage.mkdir()
            for entry in entries:
                raw = (candidate / entry["file"]).read_bytes()
                if (
                    wav_metadata(raw, identity["sample_rate"])["audio_sha256"]
                    != entry["audio_sha256"]
                ):
                    raise ValueError("Audio thay đổi trong lúc đóng gói")
                atomic_write(stage / entry["file"], raw)
                entry.update(
                    listening_status="PASS",
                    reviewer=reviewer.strip(),
                    reviewed_at=approved_at,
                    approval_method="owner_confirmation",
                )
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "catalog_version": output.name,
                "source_catalog_date": catalog["export_date"],
                "template_sha256": catalog["template_sha256"],
                "source_revision": catalog["source_revision"],
                "audio_config": identity,
                "status": "RELEASED",
                "release_ready": True,
                "approval": approval,
                "assets": entries,
                "summary": original["summary"],
                "build_usage": {
                    "successful_requests": sum(
                        a["status"] == "GENERATED" for a in original["attempts"]
                    ),
                    "characters_requested": sum(
                        a["characters_requested"]
                        for a in original["attempts"]
                        if a["status"] == "GENERATED"
                    ),
                    "billed_characters": None,
                },
            }
            atomic_write(
                stage / "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            stage.rename(output)
            return manifest
    finally:
        if stage.exists():
            # Cleanup only our verified staging directory under this release parent.
            if stage.resolve().parent != output.parent.resolve() or stage == output:
                raise ValueError("Không được xoá staging ngoài thư mục release")
            shutil.rmtree(stage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approval-note", required=True)
    args = parser.parse_args()
    if (
        not args.version
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for c in args.version)
        or args.version in (".", "..")
    ):
        parser.error("Phiên bản chỉ gồm a-z, 0-9, dấu chấm, gạch ngang và gạch dưới")
    try:
        assets, catalog = load_shortlist(args.date)
        identity = audio_config(VbeeTTSConfig())
        candidate = args.candidate or (
            ROOT / "temp/tts/static-candidate" / args.date / digest(canonical_json(identity))[:16]
        )
        output = ROOT / "assets/tts/static" / args.version
        manifest = release_candidate(
            candidate,
            output,
            assets,
            catalog,
            identity,
            reviewer=args.reviewer,
            approval_note=args.approval_note,
        )
        print(json.dumps({"directory": str(output), **manifest["summary"]}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"RELEASE ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
