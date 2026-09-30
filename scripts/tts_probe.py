"""Đo Vbee: mở kết nối mới mỗi câu (cách cũ) so với dùng lại một kết nối (cách mới, VbeeTTS).

    python scripts/tts_probe.py                    # 5 vòng x 3 loại câu x 2 cách, cách nhau 2 s
    python scripts/tts_probe.py --kinds ngan --reps 8        # rẻ nhất: ~770 ký tự
    python scripts/tts_probe.py --kinds ngan,vua --reps 4 --dry-run   # chỉ in số ký tự sẽ tốn
    python scripts/tts_probe.py --reps 10 --gap 5 --csv temp/tts/probe/ec2.csv
    python scripts/tts_probe.py --reps 0 --idle 60,120,300   # server giữ kết nối rảnh bao lâu

Trên EC2 image không có `scripts/`, nên đẩy file qua stdin (thư mục /opt/callbot):

    docker compose --env-file .env --env-file image.env exec -T bot python - --reps 5 < tts_probe.py

Script tự dựng client (cùng header, payload, timeout với VbeeTTS), nên chạy được cả trên image
chưa có bản dùng lại kết nối. Mỗi request đo `connect` (TCP + TLS; 0 nếu dùng lại kết nối),
`first_byte` (tới chunk audio đầu tiên) và `total` (nhận xong audio), tính từ lúc gửi request.
Cách mới làm một request khởi động trước khi đo, giống lượt thứ hai trở đi của một cuộc gọi.
Script không cắt ở trần `VBEE_TIMEOUT_S` như VbeeTTS; request vượt trần được đếm riêng (trên
prod những câu đó sẽ chuyển sang ElevenLabs).

Tốn quota: mặc định khoảng 4.000 ký tự Vbee; script in số dự kiến trước khi gọi. Kết nối dùng
lại chỉ bỏ phần bắt tay ở đầu request, không phụ thuộc độ dài câu, nên `--kinds ngan` đủ để so
`first_byte`. Không in text lên log nào khác.
"""

import argparse
import csv
import statistics
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import httpx

from inference.tts.config import VbeeTTSConfig
from inference.tts.providers.vbee import VbeeTTS

SENTENCES = {
    "ngan": "Dạ, anh chị cho em xin ngày tháng năm sinh ạ?",
    "vua": (
        "Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, "
        "ngày 14 tháng 10, tại Vinmec Times City ạ."
    ),
    "dai": (
        "Dạ, em chưa nghe rõ ạ. Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là "
        "3 giờ 30 chiều, ngày 14 tháng 10, tại Vinmec Times City ạ. Anh chị có đến khám "
        "được theo lịch này không ạ? Anh chị vui lòng trả lời có hoặc không giúp em ạ."
    ),
}
MODES = ("cu", "moi")


@dataclass
class Sample:
    mode: str
    kind: str
    rep: int
    new_connection: bool = False
    connect_ms: float = 0.0
    first_byte_ms: float = 0.0
    total_ms: float = 0.0
    audio_bytes: int = 0
    error: str = ""


class Probe:
    def __init__(self, config: VbeeTTSConfig) -> None:
        tts = VbeeTTS(config)
        # Dùng đúng header/payload/timeout của VbeeTTS để số đo khớp đường chạy thật
        self.endpoint = config.endpoint
        self.headers = tts._headers
        self.payload = tts._payload
        self.timeout = tts._timeout
        close = getattr(tts, "close", None)
        if close is not None:
            close()

    def client(self, keepalive_s: float) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, limits=httpx.Limits(keepalive_expiry=keepalive_s))

    def send(self, client: httpx.Client, sample: Sample, text: str) -> Sample:
        started = time.perf_counter()
        marks: dict[str, float] = {}

        def trace(event: str, info: dict) -> None:
            marks.setdefault(event, (time.perf_counter() - started) * 1000)

        try:
            with client.stream(
                "POST",
                self.endpoint,
                headers=self.headers,
                json=self.payload(text),
                timeout=self.timeout,
                extensions={"trace": trace},
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                for chunk in response.iter_bytes():
                    if chunk and not sample.first_byte_ms:
                        sample.first_byte_ms = (time.perf_counter() - started) * 1000
                    sample.audio_bytes += len(chunk)
        except Exception as exc:  # noqa: BLE001 — CLI chẩn đoán: ghi lỗi rồi đo tiếp
            sample.error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        sample.total_ms = (time.perf_counter() - started) * 1000
        tcp = marks.get("connection.connect_tcp.started")
        if tcp is not None:
            sample.new_connection = True
            done = marks.get("connection.start_tls.complete") or marks.get(
                "connection.connect_tcp.complete", tcp
            )
            sample.connect_ms = done - tcp
        return sample


def quota_chars(kinds: list[str], reps: int) -> int:
    # Mỗi vòng mỗi loại câu gửi 2 lần (cũ + mới), cộng một câu ngắn khởi động
    return reps * 2 * sum(len(SENTENCES[k]) for k in kinds) + len(SENTENCES["ngan"])


def run_compare(
    probe: Probe, keepalive_s: float, kinds: list[str], reps: int, gap_s: float
) -> list[Sample]:
    samples: list[Sample] = []
    with probe.client(keepalive_s) as warm:
        # Khởi động: lượt đầu của cuộc gọi luôn phải bắt tay, không tính vào số đo
        probe.send(warm, Sample("moi", "ngan", 0), SENTENCES["ngan"])
        for rep in range(1, reps + 1):
            for kind in kinds:
                text = SENTENCES[kind]
                # Đổi thứ tự mỗi vòng để mạng dao động không nghiêng về một cách
                for mode in MODES if rep % 2 else MODES[::-1]:
                    time.sleep(gap_s)
                    sample = Sample(mode, kind, rep)
                    if mode == "cu":
                        # Cách cũ: mỗi câu một httpx.Client mới, bắt tay TCP + TLS từ đầu
                        with probe.client(keepalive_s) as cold:
                            probe.send(cold, sample, text)
                    else:
                        probe.send(warm, sample, text)
                    samples.append(sample)
                    print(
                        f"  {mode:>3} {kind:<4} #{rep}: connect {sample.connect_ms:5.0f} ms  "
                        f"first_byte {sample.first_byte_ms:5.0f} ms  "
                        f"total {sample.total_ms:6.0f} ms"
                        + (f"  LỖI {sample.error}" if sample.error else ""),
                        flush=True,
                    )
    return samples


def run_idle(probe: Probe, idles: list[float]) -> None:
    print("\nKết nối rảnh N giây rồi gửi tiếp (dùng lại = server Vbee còn giữ kết nối):")
    # keepalive phía client rất dài để chỉ phía server quyết định đóng kết nối rảnh
    with probe.client(3600.0) as client:
        for idle in idles:
            probe.send(client, Sample("idle", "ngan", 0), SENTENCES["ngan"])
            time.sleep(idle)
            sample = probe.send(client, Sample("idle", "ngan", 0), SENTENCES["ngan"])
            if sample.error:
                state = f"LỖI {sample.error}"
            else:
                state = "mở mới" if sample.new_connection else "dùng lại"
            print(f"  rảnh {idle:5.0f} s -> {state:<12} first_byte {sample.first_byte_ms:5.0f} ms")


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[round(0.95 * (len(ordered) - 1))]


def summarize(samples: list[Sample], cap_s: float) -> None:
    print(
        "\n| Loại câu | Cách | n | Kết nối mới | Bắt tay trung vị | first_byte trung vị "
        f"| first_byte p95 | total trung vị | total p95 | > {cap_s:g} s |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for kind in SENTENCES:
        for mode in MODES:
            ok = [s for s in samples if s.kind == kind and s.mode == mode and not s.error]
            if not ok:
                continue
            first = [s.first_byte_ms for s in ok]
            total = [s.total_ms for s in ok]
            fresh = [s.connect_ms for s in ok if s.new_connection]
            handshake = f"{statistics.median(fresh):.0f} ms" if fresh else "-"
            over = sum(t > cap_s * 1000 for t in total)
            print(
                f"| {kind} | {mode} | {len(ok)} | {len(fresh)}/{len(ok)} | {handshake} | "
                f"{statistics.median(first):.0f} ms | {_p95(first):.0f} ms | "
                f"{statistics.median(total):.0f} ms | {_p95(total):.0f} ms | {over} |"
            )
    errors = [s for s in samples if s.error]
    if errors:
        print(
            f"\n{len(errors)} request lỗi: "
            + ", ".join(f"{s.mode}/{s.kind}: {s.error}" for s in errors)
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reps", type=int, default=5, help="số vòng cho mỗi loại câu và mỗi cách")
    parser.add_argument("--gap", type=float, default=2.0, help="giây nghỉ giữa hai request")
    parser.add_argument("--idle", default="", help="danh sách giây rảnh, vd. 60,120,300")
    parser.add_argument("--csv", default="", help="ghi từng request ra CSV")
    parser.add_argument(
        "--kinds",
        default=",".join(SENTENCES),
        help="loại câu cần đo, vd. ngan hoặc ngan,vua (bỏ bớt để đỡ quota)",
    )
    parser.add_argument("--dry-run", action="store_true", help="chỉ in số ký tự sẽ tốn")
    args = parser.parse_args()
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    unknown = [k for k in kinds if k not in SENTENCES]
    if unknown or not kinds:
        print(f"--kinds chỉ nhận {', '.join(SENTENCES)}", file=sys.stderr)
        return 2
    idles = [float(x) for x in args.idle.split(",") if x.strip()]
    chars = (quota_chars(kinds, args.reps) if args.reps > 0 else 0) + 2 * len(
        SENTENCES["ngan"]
    ) * len(idles)
    print(f"Dự kiến tốn {chars} ký tự quota Vbee", flush=True)
    if args.dry_run:
        return 0

    config = VbeeTTSConfig()
    try:
        probe = Probe(config)
    except ValueError as exc:
        print(f"Cấu hình: {exc}", file=sys.stderr)
        return 2
    # Image cũ chưa có VBEE_KEEPALIVE_S: dùng mặc định trong config/tts.yaml của bản mới
    keepalive_s = getattr(config, "keepalive_s", 30.0)

    samples: list[Sample] = []
    if args.reps > 0:
        print(f"Vbee {config.endpoint}, giọng {config.voice_code}, keepalive {keepalive_s:g} s")
        samples = run_compare(probe, keepalive_s, kinds, args.reps, args.gap)
        summarize(samples, config.timeout_s)
    if idles:
        run_idle(probe, idles)

    if args.csv and samples:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=[f.name for f in fields(Sample)])
            writer.writeheader()
            writer.writerows(asdict(s) for s in samples)
        print(f"\nCSV: {out}")
    return 1 if any(s.error for s in samples) else 0


if __name__ == "__main__":
    raise SystemExit(main())
