"""Build candidate Vbee audio from the exact current Engine shortlist.

    python scripts/tts_build_static.py --date 2026-10-08 --dry-run
    python scripts/tts_build_static.py --date 2026-10-08 --synthesize
    python scripts/tts_build_static.py --date 2026-10-08 --rename-files

The default only prepares the manifest, listening sheet and local review page.
--synthesize spends Vbee quota once per missing valid asset. No fallback, automatic
retry, release manifest or runtime cache activation. Resume checks text, the full
audio configuration, WAV format and checksum. Human listening remains required.
"""

import argparse
import csv
import html
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
import wave
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4

from inference.tts.config import VbeeTTSConfig
from inference.tts.providers.vbee import VbeeTTS
from inference.tts.static_identity import (
    SCHEMA_VERSION,
    cache_key,
    canonical_json,
    digest,
    vbee_audio_identity,
)

if __package__:
    from scripts.tts_utterance_catalog import TEMPLATE_PATH, build_rows
else:
    from tts_utterance_catalog import TEMPLATE_PATH, build_rows

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/evidence/tts-static-cache"
REVIEW_FIELDS = (
    "listening_status",
    "fidelity_1_0",
    "naturalness_1_5",
    "audio_cut_1_0",
    "wrong_or_missing_words",
    "pause_speed_notes",
    "reviewer",
    "reviewed_at",
    "notes",
)


def load_shortlist(export_date: str) -> tuple[list[dict], dict]:
    date.fromisoformat(export_date)
    catalog = json.loads(
        (DATA / f"tts-utterance-catalog-{export_date}.json").read_text(encoding="utf-8")
    )
    if catalog["template_sha256"] != digest(TEMPLATE_PATH.read_bytes()):
        raise ValueError("Catalog cũ: xuất lại catalog/shortlist từ Engine trước khi thu")
    current = {
        r["template_id"]: r
        for r in build_rows()
        if r["kind"] == "STATIC" and r["prebuild_candidate"]
    }
    with (DATA / f"tts-static-shortlist-{export_date}.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        assets = list(csv.DictReader(handle))
    if (
        not assets
        or len(assets) != len(current)
        or {a["template_id"] for a in assets} != set(current)
    ):
        raise ValueError("Danh sách thu không phủ đúng các câu cố định hiện tại")
    if len({a["utterance"] for a in assets}) != len(assets):
        raise ValueError("Danh sách thu trùng nguyên văn")
    for asset in assets:
        row = current[asset["template_id"]]
        text = asset["utterance"]
        if not text or text != text.strip() or len(text) >= 300:
            raise ValueError(
                f"Câu rỗng, có khoảng trắng đầu/cuối hoặc dài >= 300: {asset['template_id']}"
            )
        if (
            text != row["current_text"]
            or asset["text_sha256"] != digest(text.encode("utf-8"))
            or int(asset["character_count"]) != len(text)
            or asset["success_outcome"] != row["success_outcome"]
        ):
            raise ValueError(f"Câu/hash/metadata không khớp Engine: {asset['template_id']}")
        asset["character_count"] = len(text)
        asset["aliases"] = row["aliases"]
    return assets, catalog


def audio_config(config: VbeeTTSConfig) -> dict:
    endpoint = urlsplit(config.endpoint)
    if (
        endpoint.scheme != "https"
        or endpoint.hostname != "api.vbee.vn"
        or endpoint.path != "/v1/tts"
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or endpoint.port not in (None, 443)
    ):
        raise ValueError("Build chỉ gửi tới HTTPS api.vbee.vn/v1/tts; không đưa secret vào URL")
    if (
        config.sample_rate != 8000
        or not math.isfinite(config.speed)
        or not 0.25 <= config.speed <= 1.9
    ):
        raise ValueError("Kho ứng viên cần PCM16 mono 8 kHz và tốc độ Vbee hợp lệ")
    if not config.voice_code or config.bitrate not in (8, 16, 32, 64, 128):
        raise ValueError("Thiếu mã giọng hoặc bitrate không hợp lệ")
    return vbee_audio_identity(config)


def audio_filename(index: int, template_id: str, text: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", template_id):
        raise ValueError("ID câu không hợp lệ để đặt tên file")
    plain = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", plain)[:8]
    slug = "-".join(words)[:40].rstrip("-") or "cau-thoai"
    return f"{index:03d}_{template_id}_{slug}.wav"


def safe_audio_filename(name) -> bool:
    return isinstance(name, str) and bool(
        re.fullmatch(r"(?:[a-f0-9]{64}|[0-9]{3,}_[A-Za-z0-9_]+_[a-z0-9-]+)\.wav", name)
    )


def wav_metadata(raw: bytes, sample_rate: int = 8000) -> dict:
    try:
        with wave.open(io.BytesIO(raw), "rb") as clip:
            if (
                clip.getnchannels(),
                clip.getsampwidth(),
                clip.getframerate(),
                clip.getcomptype(),
            ) != (1, 2, sample_rate, "NONE"):
                raise ValueError("WAV không phải PCM16 mono ở tần số yêu cầu")
            frames = clip.getnframes()
            pcm = clip.readframes(frames)
        if frames <= 0 or len(pcm) != frames * 2 or not any(pcm):
            raise ValueError("WAV rỗng, cắt thiếu frames hoặc hoàn toàn im lặng")
    except (wave.Error, EOFError) as exc:
        raise ValueError("WAV không hợp lệ") from exc
    return {
        "audio_sha256": digest(raw),
        "frame_count": frames,
        "duration_ms": round(frames / sample_rate * 1000),
    }


def make_wav(result, config: dict) -> bytes:
    if (
        result.sample_rate != config["sample_rate"]
        or result.voice != config["voice"]
        or result.provider_actual not in (None, "vbee")
        or result.fallback_used
    ):
        raise ValueError("Provider/giọng/tần số không khớp cấu hình, hoặc đã fallback")
    if not result.pcm or len(result.pcm) % 2:
        raise ValueError("PCM rỗng hoặc thiếu byte cuối")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(result.sample_rate)
        clip.writeframes(result.pcm)
    raw = stream.getvalue()
    wav_metadata(raw, config["sample_rate"])
    return raw


def atomic_write(path: Path, raw: bytes) -> None:
    # Keep temporary names short even when friendly audio names are descriptive.
    temporary = path.with_name(f".tts-{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                temporary.replace(path)
                break
            except PermissionError as exc:
                # Windows file scanners may briefly hold the old destination open.
                # Retry only the atomic file operation, never the paid TTS request.
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def build_lock(out: Path):
    path = out / ".build.lock"
    try:
        handle = path.open("x", encoding="ascii")
    except FileExistsError as exc:
        raise ValueError(
            "Có job build đang chạy hoặc lock cũ; kiểm tra trước khi chạy lại"
        ) from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


def plan_build(assets: list[dict], config: dict, out: Path) -> list[dict]:
    path = out / "build_manifest.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if old and old.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Manifest schema không được hỗ trợ")
    prior = {entry["cache_key"]: entry for entry in old.get("assets", [])}
    entries = []
    for index, asset in enumerate(assets, 1):
        key = cache_key(asset["utterance"], config)
        entry = {
            **asset,
            "cache_key": key,
            "file": audio_filename(index, asset["template_id"], asset["utterance"]),
            "audio_config": config,
            "listening_status": "NOT_REVIEWED",
            "build_status": "MISSING",
        }
        previous = prior.get(key)
        if (
            previous
            and previous.get("build_status") == "GENERATED"
            and safe_audio_filename(previous.get("file"))
        ):
            # Keep existing names (including legacy hash names) until explicitly renamed.
            entry["file"] = previous["file"]
            expected = (
                previous.get("utterance") == entry["utterance"]
                and previous.get("text_sha256") == entry["text_sha256"]
                and previous.get("audio_config") == config
            )
            try:
                meta = wav_metadata((out / entry["file"]).read_bytes(), config["sample_rate"])
                expected = expected and all(previous.get(k) == v for k, v in meta.items())
            except (OSError, ValueError):
                expected = False
            if expected:
                entry.update(
                    {
                        k: previous[k]
                        for k in (
                            "audio_sha256",
                            "frame_count",
                            "duration_ms",
                            "built_at",
                            "synth_ms",
                        )
                    }
                )
                entry["build_status"] = "GENERATED"
        entries.append(entry)
    return entries


def rename_audio_files(out: Path, entries: list[dict]) -> None:
    moves = []
    for index, entry in enumerate(entries, 1):
        if entry["build_status"] != "GENERATED":
            raise ValueError("Chỉ đổi tên khi toàn bộ audio đã được kiểm hash và WAV")
        target = audio_filename(index, entry["template_id"], entry["utterance"])
        if entry["file"] != target:
            if (out / target).exists():
                raise ValueError("Tên file đích đã tồn tại; không ghi đè audio")
            moves.append((entry, entry["file"], target))
    if len({target.casefold() for _, _, target in moves}) != len(moves):
        raise ValueError("Tên file audio bị trùng")
    completed = []
    try:
        for entry, source, target in moves:
            (out / source).rename(out / target)
            entry["file"] = target
            completed.append((entry, source, target))
    except OSError:
        for entry, source, target in reversed(completed):
            (out / target).rename(out / source)
            entry["file"] = source
        raise


def review_rows(out: Path, entries: list[dict]) -> list[dict]:
    path = out / "listening_sheet.csv"
    previous = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            previous = {r["cache_key"]: r for r in csv.DictReader(handle)}
    rows = []
    for entry in entries:
        row = {
            key: entry.get(key, "")
            for key in (
                "template_id",
                "group",
                "utterance",
                "character_count",
                "cache_key",
                "audio_sha256",
                "duration_ms",
                "file",
                "build_status",
            )
        }
        row.update(dict.fromkeys(REVIEW_FIELDS, ""))
        row["listening_status"] = "NOT_REVIEWED"
        old = previous.get(entry["cache_key"])
        if old and entry.get("audio_sha256") and old.get("audio_sha256") == entry["audio_sha256"]:
            row.update({key: old.get(key, "") for key in REVIEW_FIELDS})
        rows.append(row)
    return rows


def review_page(rows: list[dict], config: dict) -> str:
    table = []
    for index, row in enumerate(rows, 1):
        audio = (
            f'<audio controls preload="none" src="{row["file"]}"></audio>'
            f'<br><a href="{html.escape(row["file"], quote=True)}" download>{html.escape(row["file"])}</a>'
            if row["build_status"] == "GENERATED"
            else "Chưa có audio"
        )
        fields = []
        for name, label, options in (
            ("listening_status", "Kết luận", ("NOT_REVIEWED", "PASS", "REVISE")),
            ("fidelity_1_0", "Đúng chữ", ("", "1", "0")),
            ("naturalness_1_5", "Tự nhiên", ("", "1", "2", "3", "4", "5")),
            ("audio_cut_1_0", "Bị cắt", ("", "0", "1")),
        ):
            opts = "".join(
                f'<option value="{v}"{" selected" if row[name] == v else ""}>{v or "—"}</option>'
                for v in options
            )
            fields.append(
                f'<label>{label} <select data-i="{index - 1}" data-k="{name}">{opts}</select></label>'
            )
        for name, label in (
            ("wrong_or_missing_words", "Chữ sai/thiếu"),
            ("pause_speed_notes", "Ngắt nghỉ/tốc độ"),
            ("reviewer", "Người nghe"),
            ("reviewed_at", "Ngày nghe"),
            ("notes", "Góp ý"),
        ):
            fields.append(
                f'<label>{label} <input data-i="{index - 1}" data-k="{name}" value="{html.escape(row[name], quote=True)}"></label>'
            )
        table.append(
            f"<tr><td>{index}<br><code>{html.escape(row['template_id'])}</code></td><td>{html.escape(row['utterance'])}</td><td>{audio}<br>{row['duration_ms'] or '—'} ms</td><td>{''.join(fields)}</td></tr>"
        )
    embedded = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html><html lang="vi"><meta charset="utf-8"><title>Nghe duyệt audio cố định Vbee</title>
<style>body{{font:15px system-ui;margin:24px;line-height:1.5}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:10px;vertical-align:top}}td:nth-child(2){{width:30%}}label{{display:block;margin:5px 0}}input{{max-width:220px}}button{{padding:10px;cursor:pointer}}audio{{width:240px}}code{{font-size:12px}}</style>
<h1>Nghe duyệt {len(rows)} câu cố định Vbee</h1>
<p>Giọng {html.escape(config["voice"])}, tốc độ {config["speed"]}, PCM16 mono {config["sample_rate"]} Hz. Audio ứng viên, chưa bật cache.</p>
<p>Nghe và đối chiếu nguyên văn từng câu. Đúng chữ: 1 đúng / 0 sai. Tự nhiên: 1–5. Bị cắt: 0 không / 1 có. Chọn PASS hoặc REVISE sau khi nghe, điền người và ngày nghe.</p>
<p>Thay đổi trên trang chỉ nằm trong trình duyệt: bấm tải phiếu trước khi đóng. Lưu CSV tải về thành listening_sheet.csv trong thư mục này để công cụ giữ kết quả khi chạy lại.</p>
<button id="download">Tải phiếu nghe CSV</button>
<table><thead><tr><th>Câu / ID</th><th>Lời bot</th><th>Audio</th><th>Đánh giá</th></tr></thead><tbody>{"".join(table)}</tbody></table>
<script>const rows={embedded};document.querySelectorAll('[data-k]').forEach(el=>el.addEventListener('change',()=>{{rows[Number(el.dataset.i)][el.dataset.k]=el.value;}}));
document.getElementById('download').onclick=()=>{{const keys=Object.keys(rows[0]);const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';const csv='\\uFEFF'+[keys.map(quote).join(','),...rows.map(row=>keys.map(k=>quote(row[k])).join(','))].join('\\r\\n')+'\\r\\n';const url=URL.createObjectURL(new Blob([csv],{{type:'text/csv;charset=utf-8'}}));const a=document.createElement('a');a.href=url;a.download='listening_sheet.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}};</script></html>"""


def write_outputs(
    out: Path, entries: list[dict], catalog: dict, config: dict, attempts: list[dict]
) -> dict:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "catalog_version": catalog["export_date"],
        "template_sha256": catalog["template_sha256"],
        "source_revision": catalog["source_revision"],
        "audio_config": config,
        "release_ready": False,
        "status": "CANDIDATE_PENDING_LISTENING",
        "assets": entries,
        "summary": {
            "total": len(entries),
            "generated": sum(e["build_status"] == "GENERATED" for e in entries),
            "characters": sum(e["character_count"] for e in entries),
        },
        "attempts": attempts,
    }
    rows = review_rows(out, entries)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(
        out / "build_manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    atomic_write(out / "listening_sheet.csv", buffer.getvalue().encode("utf-8-sig"))
    atomic_write(out / "index.html", review_page(rows, config).encode("utf-8"))
    return manifest


def run_build(
    assets: list[dict],
    catalog: dict,
    config: VbeeTTSConfig,
    out: Path,
    *,
    synthesize: bool = False,
    rename_files: bool = False,
    limit: int | None = None,
    max_characters: int = 5000,
    provider_factory: Callable = VbeeTTS,
) -> dict:
    safe = audio_config(config)
    out.mkdir(parents=True, exist_ok=True)
    with build_lock(out):
        entries = plan_build(assets, safe, out)
        if rename_files:
            if synthesize:
                raise ValueError("Đổi tên file không gọi Vbee")
            rename_audio_files(out, entries)
        pending = [e for e in entries if e["build_status"] != "GENERATED"]
        selected = pending if limit is None else pending[:limit]
        if max_characters <= 0 or (limit is not None and limit <= 0):
            raise ValueError("Limit/ngân sách ký tự phải lớn hơn 0")
        requested_chars = sum(e["character_count"] for e in selected)
        if synthesize and requested_chars > max_characters:
            raise ValueError(f"Vượt ngân sách {max_characters} ký tự: cần {requested_chars}")
        path = out / "build_manifest.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        attempts = previous.get("attempts", [])
        manifest = write_outputs(out, entries, catalog, safe, attempts)
        if synthesize and selected:
            if not config.api_token.get_secret_value() or not config.app_id:
                raise ValueError("Cần VBEE_API_TOKEN và VBEE_APP_ID trước khi gọi Vbee")
            provider = provider_factory(config)
            try:
                for entry in selected:
                    started = time.perf_counter()
                    attempt = {
                        "cache_key": entry["cache_key"],
                        "template_id": entry["template_id"],
                        "characters_requested": entry["character_count"],
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "status": "STARTED",
                        "billed_characters": None,
                    }
                    attempts.append(attempt)
                    write_outputs(out, entries, catalog, safe, attempts)
                    try:
                        result = provider.synthesize(entry["utterance"])
                        raw = make_wav(result, safe)
                        meta = wav_metadata(raw, safe["sample_rate"])
                        atomic_write(out / entry["file"], raw)
                        entry.update(meta)
                        entry.update(
                            build_status="GENERATED",
                            built_at=datetime.now(timezone.utc).isoformat(),
                            synth_ms=round((time.perf_counter() - started) * 1000),
                        )
                        attempt["status"] = "GENERATED"
                    except Exception as exc:  # noqa: BLE001 — stop on first failure; no paid retry
                        code = str(getattr(exc, "code", type(exc).__name__))
                        # Never serialize arbitrary exception messages or response bodies.
                        code = (
                            code if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code) else "BUILD_ERROR"
                        )
                        entry.update(build_status="ERROR", error_code=code)
                        attempt.update(status="ERROR", error_code=code)
                        manifest = write_outputs(out, entries, catalog, safe, attempts)
                        print(
                            f"STOP {entry['template_id']}: {code}; không tự retry", file=sys.stderr
                        )
                        return manifest
                    manifest = write_outputs(out, entries, catalog, safe, attempts)
                    print(
                        f"GENERATED {entry['template_id']}: {entry['duration_ms']} ms audio",
                        flush=True,
                    )
            finally:
                provider.close()
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--date", required=True, help="ngày của catalog/shortlist, YYYY-MM-DD")
    parser.add_argument("--out", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="không ghi file hoặc gọi provider")
    mode.add_argument("--synthesize", action="store_true", help="gọi Vbee cho các audio còn thiếu")
    mode.add_argument(
        "--rename-files", action="store_true", help="đổi tên audio đã thu; không gọi Vbee"
    )
    parser.add_argument(
        "--limit", type=int, help="giới hạn số request mới (ví dụ 1 để kiểm kết nối)"
    )
    parser.add_argument(
        "--max-characters", type=int, default=5000, help="trần ký tự gửi trong lần chạy này"
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=30.0,
        help="timeout riêng job thu offline; không đổi runtime",
    )
    args = parser.parse_args()
    try:
        assets, catalog = load_shortlist(args.date)
        base = VbeeTTSConfig()
        if not math.isfinite(args.request_timeout) or args.request_timeout <= 0:
            raise ValueError("Timeout phải hữu hạn và lớn hơn 0")
        config = base.model_copy(
            update={
                "timeout_s": args.request_timeout,
                "connect_timeout_s": min(10.0, args.request_timeout),
            }
        )
        safe = audio_config(config)
        folder = digest(canonical_json(safe))[:16]
        out = args.out or ROOT / "temp/tts/static-candidate" / args.date / folder
        entries = plan_build(assets, safe, out)
        pending = [e for e in entries if e["build_status"] != "GENERATED"]
        if args.limit is not None and args.limit <= 0 or args.max_characters <= 0:
            raise ValueError("Limit/ngân sách ký tự phải lớn hơn 0")
        selected = pending if args.limit is None else pending[: args.limit]
        report = {
            "total": len(entries),
            "characters": sum(e["character_count"] for e in entries),
            "reuse": len(entries) - len(pending),
            "pending": len(pending),
            "selected_requests": len(selected),
            "selected_characters": sum(e["character_count"] for e in selected),
            "audio_config": safe,
            "credentials_configured": bool(base.api_token.get_secret_value() and base.app_id),
            "out": str(out),
            "release_ready": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        if args.dry_run:
            return 0
        manifest = run_build(
            assets,
            catalog,
            config,
            out,
            synthesize=args.synthesize,
            rename_files=args.rename_files,
            limit=args.limit,
            max_characters=args.max_characters,
        )
        print(json.dumps(manifest["summary"], ensure_ascii=False), flush=True)
        print(f"Nghe: {out / 'index.html'}\nPhiếu: {out / 'listening_sheet.csv'}", flush=True)
        return 1 if any(e["build_status"] == "ERROR" for e in manifest["assets"]) else 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"BUILD ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Windows PowerShell may inherit a console encoding without Vietnamese support.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
