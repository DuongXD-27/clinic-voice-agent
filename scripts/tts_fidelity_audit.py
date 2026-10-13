"""Kiểm audio đọc đúng lời bot (§4.1.3) cho 5 kịch bản đang chấm: Identity, Confirm, No-answer,
Cancel, Transfer. Task 29/09 trong docs/plans/tts-w3-w6.md.

    python scripts/tts_fidelity_audit.py --dry-run          # chỉ liệt kê câu + độ dài, không gọi Vbee
    python scripts/tts_fidelity_audit.py                    # sinh WAV bằng giọng Vbee trong config/.env
    python scripts/tts_fidelity_audit.py --speed 0.9        # thử tốc độ khác, cùng giọng

`--voice` (lặp được) chỉ dùng khi thật cần so giọng: mỗi giọng tốn thêm ~3.000 ký tự quota Vbee.
Realtime sync chỉ nhận giọng có `has_tts_sync` (5 giọng Việt, 29/09); giọng khác trả 400.

Câu lấy từ registry của `templates.py` (static + renderer). Câu có phần động điền bằng 11 lịch seed
của Clinic Mock (`FakeClinicAPI.mentor_mock()`): nghe bản có phút (apt_00417) và bản dài nhất; độ
dài lớn nhất tính trên mọi lịch seed x mọi tên cơ sở. Câu nhắc im lặng lặp lại câu hỏi đang chờ nên
độ dài lớn nhất tính với câu hỏi dài nhất.

Ra `temp/tts/fidelity/`: mỗi giọng một thư mục WAV + `listening_sheet.csv` (cột trống để điền
đúng/sai, ngữ điệu 1–5, ghi chú) và `index.html` nghe các giọng cạnh nhau.
Script không sửa câu: text gửi Vbee đúng bằng utterance (§4.1.3). Không log text lên server nào khác.
"""

import argparse
import csv
import html
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from callbot.engine.dialogue import templates as t
from callbot.engine.policy.utterances import RENDERERS, STATIC_UTTERANCES
from clinic_mock_sim import FakeClinicAPI
from inference.tts.config import VbeeTTSConfig
from inference.tts.providers.vbee import MAX_TEXT_CHARS, VbeeTTS
from speech.audio.codec import encode_wav
from speech.types import AudioSegment

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "temp" / "tts" / "fidelity"
# Khoảng lặng giữa các câu trong file nghe liền
GAP_S = 1.0

# Template của 5 kịch bản đang chấm (Bảng 1 contract: tuần 2 + tuần 3)
SCENARIOS: dict[str, tuple[str, ...]] = {
    "Identity": (
        "GREETING_OUTBOUND",
        "GREETING_INBOUND",
        "GREETING_BACK_SHARED",
        "ASK_NAME_AGAIN",
        "ASK_NAME_AFTER_DOB",
        "ASK_NAME_VERIFY_SHARED",
        "ASK_NAME_DECLINED",
        "ASK_DOB",
        "ASK_DOB_VERIFY_SHARED",
        "INTRODUCE_AGAIN_ASK_DOB",
        "ASK_DOB_AGAIN",
        "ASK_DOB_INVALID",
        "ASK_DOB_DECLINED",
        "ASK_INTENT_INBOUND",
        "NOT_UNDERSTOOD",
        "HOLD",
    ),
    "Confirm": (
        "APPOINTMENT_SUMMARY",
        "ATTENDANCE_READBACK",
        "ATTENDANCE_REREAD",
        "KEEP_APPOINTMENT",
        "CONFIRMED_DONE",
        "CONFIRMED_SAFE",
    ),
    "No-answer": ("SILENCE", "SILENCE_REPROMPT", "GOODBYE_UNREACHABLE"),
    "Cancel": (
        "ASK_CHANGE_OR_CANCEL",
        "CANCEL_RECONFIRM",
        "CANCEL_CHOICE",
        "CANCEL_REASON_NOTED",
        "CANCELLED_SAFE",
        "CANCELLED_DONE",
    ),
    "Transfer": ("TRANSFER", "GREETING_HANDOFF_INBOUND"),
}
# Vào bộ test tuần 4 (Reschedule) và tuần 5 (Booking): kiểm ở task 05/10 và 12/10
DEFERRED = frozenset(
    {
        "RESCHEDULED_SAFE",
        "RESCHEDULED_DONE",
        "BOOKED_SAFE",
        "BOOKED_DONE",
        "BOOKING_ABANDONED",
        "OFFER_SLOTS",
        "SLOT_READBACK",
        "CURRENT_TIME_CHOICE",
        "SLOT_CHOICE",
    }
)
# Renderer đọc lịch hẹn: điền bằng dữ liệu seed
APPOINTMENT_RENDERERS = {
    "APPOINTMENT_SUMMARY": t.appointment_summary,
    "ATTENDANCE_READBACK": t.attendance_readback,
    "ATTENDANCE_REREAD": t.attendance_reread,
    "KEEP_APPOINTMENT": t.keep_appointment,
    "CONFIRMED_DONE": t.confirmed,
}
# Lịch có phút (3 giờ 30 chiều) — Listing 3 của contract
SAMPLE_APPOINTMENT = "apt_00417"
# Chỉ để qua assert_can_disclose: renderer không đọc gì khác từ ctx
_VERIFIED = SimpleNamespace(identity_verified=True)


@dataclass
class Sentence:
    scenario: str
    template_id: str
    variant: str
    text: str
    max_chars: int
    results: dict[str, dict] = field(default_factory=dict)


def _static_texts() -> dict[str, str]:
    return {spec.template_id: text for text, spec in STATIC_UTTERANCES.items()}


def _appointment_variants(appointments: list[dict]) -> list[tuple[str, dict]]:
    """Lịch có phút + lịch cho câu dài nhất; mọi tổ hợp lịch x cơ sở dùng cho độ dài lớn nhất."""
    by_id = {a["appointment_id"]: a for a in appointments}
    longest = max(appointments, key=lambda a: len(t.appointment_summary(_VERIFIED, a)))
    variants = [(SAMPLE_APPOINTMENT, by_id[SAMPLE_APPOINTMENT])]
    if longest["appointment_id"] != SAMPLE_APPOINTMENT:
        variants.append((longest["appointment_id"], longest))
    return variants


def _all_combinations(appointments: list[dict]) -> list[dict]:
    return [{**a, "clinic_id": clinic} for a in appointments for clinic in t.CLINIC_NAMES]


def build_sentences() -> list[Sentence]:
    statics = _static_texts()
    appointments = list(FakeClinicAPI.mentor_mock().appointments.values())
    combos = _all_combinations(appointments)
    sentences: list[Sentence] = []
    for scenario, template_ids in SCENARIOS.items():
        for template_id in template_ids:
            if template_id in APPOINTMENT_RENDERERS:
                render = APPOINTMENT_RENDERERS[template_id]
                worst = max(len(render(_VERIFIED, a)) for a in combos)
                for variant, appointment in _appointment_variants(appointments):
                    sentences.append(
                        Sentence(
                            scenario, template_id, variant, render(_VERIFIED, appointment), worst
                        )
                    )
            elif template_id == "CANCELLED_DONE":
                # Cùng text với CANCELLED_SAFE: đã nghe ở dòng đó
                continue
            elif template_id == "SILENCE_REPROMPT":
                continue  # thêm sau khi có mọi câu hỏi
            else:
                text = statics[template_id]
                sentences.append(Sentence(scenario, template_id, "", text, len(text)))

    # Nhắc im lặng = SILENCE + nguyên văn câu hỏi đang chờ (T-08): nghe với câu hỏi ngắn và câu
    # đọc lịch; độ dài lớn nhất lấy theo câu hỏi dài nhất của 5 kịch bản
    questions = [s for s in sentences if s.text.rstrip().endswith("?")]
    worst_question = max(questions, key=lambda s: s.max_chars)
    worst = len(t.SILENCE) + 1 + worst_question.max_chars
    for inner in (statics["ASK_DOB"], _find(sentences, "APPOINTMENT_SUMMARY").text):
        sentences.append(
            Sentence("No-answer", "SILENCE_REPROMPT", "", t.silence_reprompt(inner), worst)
        )
    return sentences


def _find(sentences: list[Sentence], template_id: str) -> Sentence:
    return next(s for s in sentences if s.template_id == template_id)


def check_coverage() -> list[str]:
    """Template mới đăng ký mà chưa xếp vào kịch bản nào — để không sót câu khi nghe."""
    known = {tid for ids in SCENARIOS.values() for tid in ids} | DEFERRED
    registered = set(_static_texts()) | set(RENDERERS)
    return sorted(registered - known)


def _wav_name(index: int, sentence: Sentence) -> str:
    return f"{index:02d}_{sentence.template_id}{'_' + sentence.variant if sentence.variant else ''}.wav"


def combine(sentences: list[Sentence], label: str, out: Path) -> tuple[Path, Path]:
    """Ghép mọi câu thành một WAV (cách nhau GAP_S giây) + file mốc thời gian để nghe liền một lượt."""
    combined = bytearray()
    marks = []
    rate = None
    for index, sentence in enumerate(sentences, 1):
        path = out / label / _wav_name(index, sentence)
        if not path.exists():
            marks.append(f"--:--  {index:02d} {sentence.template_id}  (không có audio)")
            continue
        with wave.open(str(path), "rb") as clip:
            rate = rate or clip.getframerate()
            if clip.getframerate() != rate:
                raise ValueError(f"{path.name}: {clip.getframerate()} Hz, khác {rate} Hz")
            start_s = len(combined) // 2 / rate
            combined += clip.readframes(clip.getnframes())
        combined += b"\x00\x00" * int(GAP_S * rate)
        minutes, seconds = divmod(int(start_s), 60)
        marks.append(
            f"{minutes:02d}:{seconds:02d}  {index:02d} [{sentence.scenario}] "
            f"{sentence.template_id} {sentence.variant}\n       {sentence.text}"
        )
    if rate is None:
        raise FileNotFoundError(f"không có WAV nào trong {out / label}")
    wav_path = out / f"{label}_tat_ca.wav"
    wav_path.write_bytes(encode_wav(AudioSegment(pcm=bytes(combined), sample_rate=rate)))
    marks_path = out / f"{label}_moc_thoi_gian.txt"
    # BOM để Notepad / PowerShell 5.1 trên Windows đọc đúng tiếng Việt
    marks_path.write_text("\n".join(marks) + "\n", encoding="utf-8-sig")
    return wav_path, marks_path


def synthesize_all(sentences: list[Sentence], voice: str, speed: float, out: Path) -> str:
    label = f"{voice}@{speed:g}"
    wav_dir = out / label
    wav_dir.mkdir(parents=True, exist_ok=True)
    provider = VbeeTTS(VbeeTTSConfig(voice_code=voice, speed=speed))
    for index, sentence in enumerate(sentences, 1):
        name = _wav_name(index, sentence)
        started = time.perf_counter()
        try:
            result = provider.synthesize(sentence.text)
        except Exception as exc:  # noqa: BLE001 — ghi lỗi vào bảng, chạy tiếp câu sau
            sentence.results[label] = {
                "error": f"{type(exc).__name__}: {getattr(exc, 'code', exc)}"
            }
            print(f"  [{label}] {name}: LỖI {sentence.results[label]['error']}", file=sys.stderr)
            continue
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        segment = AudioSegment(pcm=result.pcm, sample_rate=result.sample_rate)
        (wav_dir / name).write_bytes(encode_wav(segment))
        sentence.results[label] = {
            "wav": f"{label}/{name}",
            "synth_ms": elapsed_ms,
            "audio_ms": segment.duration_ms,
        }
        print(f"  [{label}] {name}: {elapsed_ms} ms sinh, {segment.duration_ms} ms audio")
    return label


def write_sheet(sentences: list[Sentence], labels: list[str], out: Path) -> Path:
    path = out / "listening_sheet.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        header = ["kich_ban", "template_id", "lich_mau", "so_ky_tu", "so_ky_tu_max", "text"]
        for label in labels:
            header += [
                f"{label} | wav",
                f"{label} | sinh_ms",
                f"{label} | doc_dung (1/0)",
                f"{label} | ngu_dieu (1-5)",
            ]
        header.append("ghi_chu")
        writer.writerow(header)
        for s in sentences:
            row = [s.scenario, s.template_id, s.variant, len(s.text), s.max_chars, s.text]
            for label in labels:
                result = s.results.get(label, {})
                row += [
                    result.get("wav") or result.get("error", ""),
                    result.get("synth_ms", ""),
                    "",
                    "",
                ]
            row.append("")
            writer.writerow(row)
    return path


def write_index(sentences: list[Sentence], labels: list[str], out: Path) -> Path:
    head = "".join(f"<th>{html.escape(label)}</th>" for label in labels)
    rows = []
    for s in sentences:
        cells = []
        for label in labels:
            result = s.results.get(label, {})
            if "wav" in result:
                cells.append(
                    f'<td><audio controls preload="none" src="{html.escape(result["wav"])}"></audio>'
                    f"<br><small>{result['audio_ms']} ms audio · sinh {result['synth_ms']} ms</small></td>"
                )
            else:
                cells.append(f"<td class=err>{html.escape(result.get('error', '—'))}</td>")
        flag = " class=over" if s.max_chars > MAX_TEXT_CHARS else ""
        rows.append(
            f"<tr><td>{s.scenario}</td><td><code>{s.template_id}</code> {s.variant}</td>"
            f"<td{flag}>{len(s.text)} / max {s.max_chars}</td><td>{html.escape(s.text)}</td>"
            + "".join(cells)
            + "</tr>"
        )
    page = f"""<!doctype html><meta charset="utf-8"><title>TTS fidelity 5 kịch bản</title>
<style>body{{font:14px system-ui;margin:16px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}
td:nth-child(4){{max-width:420px}}.over{{background:#fdd}}.err{{color:#b00}}audio{{width:220px}}</style>
<h1>Kiểm audio đọc đúng lời bot — 5 kịch bản</h1>
<p>Nghe từng câu: đọc đúng chữ không (thêm/bớt/sai chữ), ngữ điệu (ngang/tự nhiên), ngắt nghỉ. Điền vào <code>listening_sheet.csv</code>.</p>
<table><tr><th>Kịch bản</th><th>Template</th><th>Ký tự</th><th>Câu (utterance)</th>{head}</tr>
{"".join(rows)}</table>"""
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--voice", action="append", help="mã giọng Vbee, lặp để so nhiều giọng")
    parser.add_argument("--speed", type=float, default=None, help="ghi đè VBEE_SPEED")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="chỉ liệt kê câu và độ dài")
    parser.add_argument(
        "--combine-only",
        action="store_true",
        help="chỉ ghép lại WAV đã sinh thành một file, không gọi Vbee",
    )
    args = parser.parse_args()

    missing = check_coverage()
    if missing:
        print(f"CẢNH BÁO: template chưa xếp kịch bản: {', '.join(missing)}", file=sys.stderr)

    sentences = build_sentences()
    over = [s for s in sentences if s.max_chars > MAX_TEXT_CHARS]
    for s in sentences:
        mark = "  >300!" if s.max_chars > MAX_TEXT_CHARS else ""
        print(
            f"{s.scenario:<10} {s.template_id:<24} {s.variant:<10} {len(s.text):>3}/{s.max_chars:>3}{mark}  {s.text}"
        )
    print(
        f"\n{len(sentences)} câu; {len(over)} câu có thể vượt {MAX_TEXT_CHARS} ký tự (Vbee từ chối -> ElevenLabs)"
    )
    if args.dry_run:
        return 0

    base = VbeeTTSConfig()
    voices = args.voice or [base.voice_code]
    speed = args.speed if args.speed is not None else base.speed
    if args.combine_only:
        for voice in voices:
            wav_path, marks_path = combine(sentences, f"{voice}@{speed:g}", args.out)
            print(f"\nNghe liền: {wav_path}\nMốc thời gian: {marks_path}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    labels = []
    for voice in voices:
        print(f"\nSinh {len(sentences)} câu bằng {voice} speed={speed:g}")
        labels.append(synthesize_all(sentences, voice, speed, args.out))
    sheet = write_sheet(sentences, labels, args.out)
    index = write_index(sentences, labels, args.out)
    print(f"\nPhiếu nghe: {sheet}\nNghe trên trình duyệt: {index}")
    for label in labels:
        wav_path, marks_path = combine(sentences, label, args.out)
        print(f"Nghe liền: {wav_path}\nMốc thời gian: {marks_path}")
    errors = sum("error" in s.results.get(label, {}) for s in sentences for label in labels)
    print(f"Lỗi sinh: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
