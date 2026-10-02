#!/usr/bin/env bash
# Chạy trọn bộ benchmark trên EC2 cho một nhãn (vd. truoc / sau), lưu vào bench-results/<nhãn>/.
#
#   cd /opt/callbot
#   bash bench/run.sh truoc --dry-run            # chỉ in quota dự kiến từng phần
#   bash bench/run.sh truoc                      # profile quick, đủ 3 phần
#   bash bench/run.sh sau --profile full         # thêm cancel, fallback ElevenLabs, nói chen
#   bash bench/run.sh sau --parts tts,livekit    # chỉ chạy một số phần
#   bash bench/run.sh truoc --appointment apt_00426   # lịch hẹn khác cho phần HTTP / LiveKit
#   python3 bench/compare.py bench-results/truoc bench-results/sau > bench-results/so-sanh.md
#
# Chỉ ghi vào bench-results/ và /tmp trong container; không đụng .env hay file khác ở /opt/callbot.
set -euo pipefail

LABEL="${1:?Cần nhãn, vd. truoc hoặc sau}"
shift
PROFILE=quick
PARTS=tts,http,livekit
DRY=""
APPOINTMENT=apt_00427
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --parts) PARTS="$2"; shift 2 ;;
    --dry-run) DRY=--dry-run; shift ;;
    --appointment) APPOINTMENT="$2"; shift 2 ;;
    *) echo "Không hiểu tham số: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(dirname "$HERE")"  # /opt/callbot: nơi có .env, image.env, docker compose
C=(docker compose --env-file .env --env-file image.env)
IMAGE="$(grep -E '^IMAGE=' image.env | cut -d= -f2- || true)"
OUT="bench-results/$LABEL"
ARGS=(--label "$LABEL" --image "$IMAGE" --profile "$PROFILE" $DRY)
CALL_ARGS=("${ARGS[@]}" --appointment "$APPOINTMENT")

has() { [[ ",$PARTS," == *",$1,"* ]]; }

for service in bot livekit-worker; do
  "${C[@]}" exec -T "$service" mkdir -p /tmp/bench
  "${C[@]}" cp "$HERE/." "$service:/tmp/bench" >/dev/null
done

if [[ -n "$DRY" ]]; then
  has tts && "${C[@]}" exec -T livekit-worker python /tmp/bench/tts_component.py "${ARGS[@]}"
  has http && "${C[@]}" exec -T bot python /tmp/bench/http_turns.py "${CALL_ARGS[@]}"
  has livekit && "${C[@]}" exec -T bot python /tmp/bench/livekit_call.py "${CALL_ARGS[@]}"
  exit 0
fi

if [[ -e "$OUT" ]]; then
  echo "Đã có $OUT — đổi nhãn hoặc xoá thư mục đó trước" >&2
  exit 1
fi
mkdir -p "$OUT"
echo "Image: $IMAGE · profile: $PROFILE · phần: $PARTS → $OUT" >&2

if has tts; then
  echo "== Phần 1: TTS (livekit-worker)" >&2
  "${C[@]}" exec -T livekit-worker python /tmp/bench/tts_component.py "${ARGS[@]}" > "$OUT/tts.json"
fi
if has http; then
  echo "== Phần 2: HTTP như harness (bot → Caddy)" >&2
  "${C[@]}" exec -T bot python /tmp/bench/http_turns.py "${CALL_ARGS[@]}" > "$OUT/http.json"
  "${C[@]}" exec -T bot python /tmp/bench/traces.py --from-json - < "$OUT/http.json" > "$OUT/http_traces.json" || true
fi
if has livekit; then
  echo "== Phần 3: cuộc gọi LiveKit (bot đóng vai người gọi)" >&2
  "${C[@]}" exec -T bot python /tmp/bench/livekit_call.py "${CALL_ARGS[@]}" > "$OUT/livekit.json"
  "${C[@]}" exec -T livekit-worker python /tmp/bench/traces.py --from-json - < "$OUT/livekit.json" > "$OUT/livekit_traces.json" || true
fi

python3 "$HERE/compare.py" "$OUT" > "$OUT/summary.md"
echo "Xong. Tóm tắt: $OUT/summary.md" >&2
cat "$OUT/summary.md"
