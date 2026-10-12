"""Đo ngắt lời (barge-in) khi bot đang nói, có tiếng bot vọng lại (echo), qua đúng STTPipeline +
TurnController + InterruptionController (bench.run_pipeline với `BotTurn`).

Câu bot (`--bot-audio`): `static` (mặc định) = audio Vbee của cache TTS tĩnh đang phát trên
production (`assets/tts/static/2026-10-08-v1`, đúng chữ template hiện tại), 8 kHz đưa lên 16 kHz;
`wav` = 12 câu TTS sinh 30/09 (`temp/noise-bench/bot_tts.wav`, đo Quail) — đọc câu thoại TRƯỚC đợt
chuẩn hoá 08/10 ("Dạ Vinmec xin nghe, em là trợ lý ảo AI của tổng đài…") nên lệch chữ với template
hiện tại: chữ bot vọng lại không khớp câu bot, so khớp tiếng vọng thất bại (bot "tự ngắt lời" 6/12 câu
ở web echo −30 dB là do lệch này). Chỉ dùng `wav` để so với số đo cũ.

Echo: kênh `phone` = câu bot qua G.711 xuống máy người gọi, trễ `ECHO_DELAY_S`, vọng lại qua
G.711 lên (AEC của máy/nhà mạng không khử hết); kênh `web` = trễ + suy giảm, không codec. Mức
`echo@-20` = echo nhỏ hơn giọng người gọi (trung vị bộ câu) 20 dB.

Ba loại trial, bot bắt đầu nói ở `BOT_START_S`:
- `echo_only`: người gọi im lặng. Ngắt lời được xác nhận = ngắt lời GIẢ (bot bị cắt vì chính
  tiếng mình); ứng viên = lần bot sẽ bị tạm dừng nếu có cơ chế tạm dừng -> phát tiếp.
- `caller`: người gọi (bộ short + web) chen vào sau `BARGE_AFTER_S`. Cần được xác nhận; đo trễ
  từ lúc người gọi bắt đầu nói tới lúc ứng viên / xác nhận.
- `other`: người KHÁC (bộ golden) chen vào cùng lúc. Lý tưởng là không xác nhận (cổng giọng
  người gọi); hiện tại đo để làm mốc.
- `repeat`: người gọi lặp lại chữ bot VỪA nói ("đặt lịch khám ngày mai") trong lúc bot còn nói:
  `REPEAT_S` đầu câu bot (giọng TTS, mức như người gọi) phát từ `REPEAT_AFTER_S`. Bỏ echo theo
  chữ không được ăn mất phần này.
- `repeat_real`: GIỌNG THẬT người gọi nói lại cụm chữ của câu bot ("HỌ VÀ TÊN ĐẦY ĐỦ CỦA ANH LÀ…",
  "ANH CẦN EM HỖ TRỢ…"), cắt từ dump LiveKit (`temp/noise-bench/real_repeat_candidates.json`,
  sinh bởi temp/noise-bench/mine_real_repeats.py), ghép với câu bot có cụm đó; bắt đầu nói
  `REAL_REACTION_S` sau khi bot đọc xong cụm, nhưng bot còn nói ít nhất `MIN_OVERLAP_S`.
Chữ chuẩn của `caller`/`repeat`/`repeat_real` = ASR của chính đoạn đó, không echo, không nhiễu.

Vị trí (`--positions`): `first` = câu bot đầu tiên của cuộc gọi; `later` = trước đó bot đã đọc
trọn `PRIOR_BOTS` (người gọi im, cùng mức echo) — trạng thái đường truyền đã có bằng chứng.

Mỗi loại: `false_turns` (trial có lượt khác rỗng — với echo_only là echo thành lượt),
`word_loss` (tỉ lệ chữ người gọi mất, trung bình), `full_loss` (trial người gọi có nói mà không
còn chữ nào), `bot_mixed` (trial có lượt chứa >= 3 chữ liền của câu bot mà người gọi không
nói), `bot_words` (số chữ của các câu bot có trong lượt mà người gọi không nói, trung bình),
`false_barge_in` (ngắt lời được xác nhận khi người gọi chưa nói), `latency` (từ lúc người gọi
nói xong tới lượt đầu tiên có chữ của họ, giây ảo; decode đoạn rời đo riêng `batch_decode`).

Chạy (từ gốc repo):
    PYTHONPATH=src python eval/noise-bench/barge_in_eval.py --label base
Kết quả: temp/noise-bench/results/barge_<label>.json
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("bench", HERE / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

from callbot.engine.dialogue import templates as t  # noqa: E402
from speech.turn.controller import spoken_words  # noqa: E402

RATE = bench.RATE
BOT_START_S = 0.5
BARGE_AFTER_S = 1.0
TAIL_S = 3.0
ECHO_DELAY_S = 0.08
REPEAT_S = 1.5
REPEAT_AFTER_S = 2.0
REAL_REACTION_S = 0.2
MIN_OVERLAP_S = 0.8
PRIOR_GAP_S = 1.0
# Thứ tự câu trong bot_tts.wav (sinh bởi script đo Quail, commit c01feec).
_BOT_TEMPLATES = (
    t.GREETING_INBOUND, t.ASK_DOB, t.ASK_NAME_AGAIN, t.ASK_DOB_AGAIN, t.ASK_INTENT_INBOUND,
    t.ASK_CHANGE_OR_CANCEL, t.ASK_ATTENDANCE, t.NOT_UNDERSTOOD, t.SILENCE,
    t.CANCEL_RECONFIRM, t.TRANSFER, t.GOODBYE_UNREACHABLE,
)  # fmt: skip
# Cache TTS tĩnh không có ASK_ATTENDANCE (luôn đi kèm thông tin lịch): thay bằng câu hỏi có/không
# cùng loại.
STATIC_TTS_DIR = bench.ROOT / "assets" / "tts" / "static" / "2026-10-08-v1"
_STATIC_BOT_TEMPLATES = tuple(
    t.CONFIRM_CONFLICT if text == t.ASK_ATTENDANCE else text for text in _BOT_TEMPLATES
)
# Câu bot đọc trọn trước câu thử ở vị trí `later` (lời chào + hỏi lại khi im lặng).
PRIOR_BOTS = (t.GREETING_INBOUND, t.ASK_NAME_AGAIN)
REAL_REPEATS = bench.WORK_DIR / "real_repeat_candidates.json"


def load_bot_sentences(source: str = "static") -> list[tuple[str, np.ndarray]]:
    if source == "static":
        return _load_static_bot_sentences()
    samples, _ = bench._read_wav(bench.WORK_DIR / "bot_tts.wav")
    gap = int(0.25 * RATE)
    pieces, start, zeros = [], 0, 0
    for i, value in enumerate(samples):
        zeros = zeros + 1 if value == 0 else 0
        if zeros == gap:
            piece = samples[start : i - gap + 1]
            if len(piece) > RATE // 2:
                pieces.append(piece.astype(np.float64))
            start = i + 1
        elif zeros > gap:
            start = i + 1
    if len(samples) - start > RATE // 2:
        pieces.append(samples[start:].astype(np.float64))
    if len(pieces) != len(_BOT_TEMPLATES):
        raise RuntimeError(f"bot_tts.wav cắt ra {len(pieces)} câu, cần {len(_BOT_TEMPLATES)}")
    return list(zip(_BOT_TEMPLATES, pieces, strict=True))


def _load_static_bot_sentences() -> list[tuple[str, np.ndarray]]:
    manifest = json.loads((STATIC_TTS_DIR / "manifest.json").read_text(encoding="utf-8"))
    files = {asset["utterance"]: asset["file"] for asset in manifest["assets"]}
    sentences = []
    for text in _STATIC_BOT_TEMPLATES:
        if text not in files:
            raise RuntimeError(f"cache TTS tĩnh không có câu {text!r}")
        samples, rate = bench._read_wav(STATIC_TTS_DIR / files[text])
        sentences.append((text, bench._to_16k(samples, rate).astype(np.float64)))
    return sentences


def make_echo(
    bot: np.ndarray, total: int, level_rms: float, channel: str, start_s: float = BOT_START_S
) -> np.ndarray:
    echo = np.zeros(total, dtype=np.float64)
    start = int((start_s + ECHO_DELAY_S) * RATE)
    downlink = bench.phone_channel(bot) if channel == "phone" else bot
    end = min(total, start + len(downlink))
    echo[start:end] = downlink[: end - start]
    echo *= level_rms / max(bench._active_rms(downlink.astype(np.float64)), 1.0)
    return bench.phone_channel(echo).astype(np.float64) if channel == "phone" else echo


def trial(
    speech: np.ndarray | None,
    bot_len: int,
    channel: str,
    rng,
    after_s: float = BARGE_AFTER_S,
    bot_start_s: float = BOT_START_S,
) -> np.ndarray:
    total = int(bot_start_s * RATE) + bot_len + int(TAIL_S * RATE)
    mix = rng.normal(0.0, 1.0, total)
    if speech is not None:
        at = int((bot_start_s + after_s) * RATE)
        end = min(total, at + len(speech))
        mix[at:end] += speech[: end - at]
    pcm = np.clip(np.round(mix), -32768, 32767).astype(np.int16)
    return bench.phone_channel(pcm) if channel == "phone" else pcm


def _p(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 3) if values else None


def _mean(values: list[float]) -> float | None:
    return round(float(np.mean(values)), 3) if values else None


def _words(text: str) -> list[str]:
    return spoken_words(text).split()


def _recall(reference: str, turns: list[str]) -> float | None:
    ref = _words(reference)
    if not ref:
        return None
    heard = _words(" ".join(turns))
    return sum(min(ref.count(w), heard.count(w)) for w in set(ref)) / len(ref)


def _bot_words(turns: list[str], bot_texts: list[str], reference: str) -> int:
    """Số chữ (đếm theo túi chữ) của các câu bot có trong lượt mà người gọi không nói."""
    bot = set(_words(" ".join(bot_texts)))
    heard, said = _words(" ".join(turns)), _words(reference)
    extra = [w for w in set(heard) if w in bot]
    return sum(max(0, heard.count(w) - said.count(w)) for w in extra)


def _phrase_end_s(bot_text: str, bot_len_s: float, phrase: str) -> float | None:
    """Lúc bot đọc xong `phrase` (ước theo vị trí ký tự trong câu)."""
    words, target = _words(bot_text), _words(phrase)
    for i in range(len(words) - len(target) + 1):
        if words[i : i + len(target)] == target:
            done = len(" ".join(words[: i + len(target)]))
            return bot_len_s * done / len(" ".join(words))
    return None


def load_real_repeats(bots: list[tuple[str, np.ndarray]]) -> list[dict]:
    """Câu thật người gọi nói lại cụm >= 3 chữ của một trong các câu bot có audio."""
    import difflib

    if not REAL_REPEATS.exists():
        return []
    items = []
    for row in json.loads(REAL_REPEATS.read_text(encoding="utf-8")):
        data = (bench.ROOT / "temp/audio" / row["file"]).read_bytes()[44:]
        audio = np.frombuffer(data[: len(data) - len(data) % 2], dtype=np.int16)
        clip = audio[row["start"] : row["end"]].astype(np.float64)
        said = _words(row["text"])
        best = (0, None, "")
        for text, bot_audio in bots:
            bot = _words(text)
            m = difflib.SequenceMatcher(None, said, bot, autojunk=False).find_longest_match()
            if m.size > best[0]:
                best = (m.size, (text, bot_audio), " ".join(bot[m.b : m.b + m.size]))
        if best[0] < 3:
            continue
        text, bot_audio = best[1]
        bot_len_s = len(bot_audio) / RATE
        end_s = _phrase_end_s(text, bot_len_s, best[2]) or 0.0
        after_s = max(0.5, min(end_s + REAL_REACTION_S, bot_len_s - MIN_OVERLAP_S))
        items.append(
            {
                "speech": clip,
                "text": row["text"],
                "bot": best[1],
                "after_s": after_s,
                "wav": row["wav"],
            }
        )
    return items


def _bot_mixed(turns: list[str], bot_text: str, reference: str) -> bool:
    """Có lượt chứa >= 3 chữ liền của câu bot mà người gọi không nói."""
    import difflib

    bot, said = _words(bot_text), " ".join(_words(reference))
    for turn in turns:
        words = _words(turn)
        matcher = difflib.SequenceMatcher(None, words, bot, autojunk=False)
        for block in matcher.get_matching_blocks():
            run = " ".join(words[block.a : block.a + block.size])
            if block.size >= 3 and run not in said:
                return True
    return False


def run(
    label: str,
    channels: list[str],
    echo_levels: list[float],
    overrides: dict,
    positions: list[str],
    kinds: list[str],
    bot_audio: str = "static",
) -> dict:
    settings = bench.SpeechSettings(**{**bench.PROFILES["production"], **overrides})
    asr = bench.SpeechRecognizer(bench.create_asr_gateway(settings.asr_provider))
    bots = load_bot_sentences(bot_audio)
    by_text = dict(bots)
    model_path = settings.silero_vad_model_path
    callers = bench.build_short_set(asr, model_path) + bench.build_web_set(asr, model_path)[:20]
    others = bench.load_golden()[:20]
    caller_rms = float(np.median([bench._active_rms(c["speech"]) for c in callers]))

    def heard(clip: np.ndarray) -> str:
        pcm = np.clip(np.round(clip), -32768, 32767).astype(np.int16).tobytes()
        return asr.transcribe(bench.AudioSegment(pcm=pcm, sample_rate=RATE)).text

    for caller in callers:
        caller["text"] = heard(caller["speech"])
    repeats = []
    for text, bot_audio in bots:
        if len(bot_audio) < (REPEAT_AFTER_S + 0.5) * RATE:
            continue  # bot phải còn nói lúc người gọi lặp lại
        clip = bot_audio[: int(REPEAT_S * RATE)]
        clip = clip * caller_rms / max(bench._active_rms(clip), 1.0)
        repeats.append(
            {
                "speech": clip,
                "text": heard(clip),
                "bot": (text, bot_audio),
                "after_s": REPEAT_AFTER_S,
            }
        )
    sets = {
        "echo_only": [{}] * len(bots),
        "caller": callers,
        "other": others,
        "repeat": repeats,
        "repeat_real": load_real_repeats(bots),
    }
    results: dict = {
        "label": label,
        "settings": overrides,
        "bot_audio": bot_audio,
        "conditions": {},
    }
    for channel in channels:
        for level_db in echo_levels:
            for position in positions:
                rng = np.random.default_rng(7)
                level_rms = caller_rms * 10 ** (level_db / 20)
                rows: dict[str, list[dict]] = {kind: [] for kind in kinds}
                jobs = [(kind, item) for kind in kinds for item in sets[kind]]
                for idx, (kind, item) in enumerate(jobs):
                    text, bot_audio = item.get("bot") or bots[idx % len(bots)]
                    speech = item.get("speech")
                    after_s = item.get("after_s", BARGE_AFTER_S)
                    priors = [p for p in PRIOR_BOTS if p != text] if position == "later" else []
                    start_s, turns = BOT_START_S, []
                    for prior in priors:
                        prior_audio = by_text[prior]
                        turns.append((start_s, prior, prior_audio))
                        start_s += len(prior_audio) / RATE + PRIOR_GAP_S
                    turns.append((start_s, text, bot_audio))
                    pcm = trial(speech, len(bot_audio), channel, rng, after_s, bot_start_s=start_s)
                    bot_turns = [
                        bench.BotTurn(
                            at,
                            at + len(audio) / RATE + ECHO_DELAY_S,
                            said,
                            make_echo(audio, len(pcm), level_rms, channel, start_s=at),
                            audio,
                        )
                        for at, said, audio in turns
                    ]
                    out = asyncio.run(bench.run_pipeline(pcm, settings, asr, bot=bot_turns))
                    onset = start_s + after_s
                    speech_end = onset + len(speech) / RATE if speech is not None else None
                    reference = (
                        item.get("text", "") if kind in ("caller", "repeat", "repeat_real") else ""
                    )
                    ref_words = set(_words(reference))
                    candidates = [c for c in out["barge_in_candidates"] if c >= onset]
                    barge = out["barge_in_at"]
                    first_own = next(
                        (
                            at
                            for turn, at in zip(out["turns"], out["turn_times"], strict=True)
                            if ref_words & set(_words(turn))
                        ),
                        None,
                    )
                    recall = _recall(reference, out["turns"])
                    rows[kind].append(
                        {
                            "bot": text[:40],
                            "wav": item.get("wav"),
                            "candidates": out["barge_in_candidates"],
                            "barge_in_at": barge,
                            "candidate_delay": round(candidates[0] - onset, 3)
                            if candidates
                            else None,
                            "confirm_delay": round(barge - onset, 3)
                            if barge is not None and speech is not None and barge >= onset
                            else None,
                            "false_barge_in": barge is not None
                            and (speech is None or barge < onset),
                            "turns": out["turns"],
                            "reference": reference,
                            "recall": recall,
                            "full_loss": recall == 0.0,
                            "bot_mixed": _bot_mixed(out["turns"], text, reference),
                            "bot_words": _bot_words(
                                out["turns"], [t for _, t, _ in turns], reference
                            ),
                            "latency": round(first_own - speech_end, 3)
                            if first_own is not None and speech_end is not None
                            else None,
                            "batch_decode": round(sum(out["batch_decode_s"]), 3),
                        }
                    )
                summary = {}
                for kind, items in rows.items():
                    confirm = [r["confirm_delay"] for r in items if r["confirm_delay"] is not None]
                    latency = [r["latency"] for r in items if r["latency"] is not None]
                    recalls = [r["recall"] for r in items if r["recall"] is not None]
                    decodes = [r["batch_decode"] for r in items if r["batch_decode"]]
                    summary[kind] = {
                        "trials": len(items),
                        "false_turns": sum(any(x.strip() for x in r["turns"]) for r in items)
                        if kind == "echo_only"
                        else None,
                        "word_loss": _mean([1 - r for r in recalls]),
                        "full_loss": sum(r["full_loss"] for r in items),
                        "bot_mixed": sum(r["bot_mixed"] for r in items),
                        "bot_words": _mean([r["bot_words"] for r in items]),
                        "false_barge_in": sum(r["false_barge_in"] for r in items),
                        "confirmed": sum(r["barge_in_at"] is not None for r in items),
                        "confirm_delay_p50": _p(confirm, 50),
                        "latency_p50": _p(latency, 50),
                        "latency_p90": _p(latency, 90),
                        "batch_decode_p50": _p(decodes, 50),
                    }
                key = f"{channel}/echo@{level_db:g}/{position}"
                results["conditions"][key] = {"summary": summary, "rows": rows}
                print(f"[{label}] {key:22} {json.dumps(summary, ensure_ascii=False)}", flush=True)
    out_path = bench.WORK_DIR / "results" / f"barge_{label}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out_path.relative_to(bench.ROOT)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--channels", default="phone,web")
    parser.add_argument("--echo-levels", default="-30,-20,-10")
    parser.add_argument("--positions", default="first")
    parser.add_argument("--kinds", default="echo_only,caller,other,repeat,repeat_real")
    parser.add_argument("--bot-audio", choices=("static", "wav"), default="static")
    parser.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ")
    args = parser.parse_args()
    overrides = dict(item.split("=", 1) for item in args.set)
    levels = [float(x) for x in args.echo_levels.split(",")]
    run(
        args.label,
        args.channels.split(","),
        levels,
        overrides,
        args.positions.split(","),
        args.kinds.split(","),
        args.bot_audio,
    )


if __name__ == "__main__":
    main()
