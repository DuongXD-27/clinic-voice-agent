import { DatabaseZap } from "lucide-react";
import { useRef, useState } from "react";

import { CallPanel } from "../../components/chat/CallPanel";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { Notice } from "../../components/ui/Notice";
import { resetClinic } from "../call/api";
import { ExtractionPanel } from "../call/components/ExtractionPanel";
import { useClinicFixtures } from "../call/useClinicFixtures";
import { EventLog } from "./components/EventLog";
import { LiveKitConfigPanel } from "./components/LiveKitConfigPanel";
import { VoiceDock } from "./components/VoiceDock";
import styles from "./LiveKitPage.module.css";
import { DEFAULT_LIVEKIT_CONFIG, type LiveKitConfig } from "./model/config";
import { describeConnection, isActive, type LiveKitSession } from "./model/session";
import { toChatMessage } from "./model/transcript";
import { useLiveKitCall } from "./useLiveKitCall";

/** Thẻ trích xuất khi chưa có gì để hiện, theo `extractionIssue` của câu bot gần nhất. */
const EXTRACTION_ISSUES = {
  none: "Chưa có lượt nào.",
  missing: "Bot không gửi trích xuất: worker tắt demo_debug (config/livekit.yaml) hoặc là bản cũ.",
  invalid: "Trích xuất bot gửi sai dạng: worker và trang có thể lệch phiên bản.",
} as const;

export function LiveKitPage() {
  const [config, setConfig] = useState<LiveKitConfig>(DEFAULT_LIVEKIT_CONFIG);
  const { fixtures, reload: reloadFixtures } = useClinicFixtures();
  const audio = useRef<HTMLAudioElement>(null);
  const [resetting, setResetting] = useState(false);
  const { session, connect, toggleMic, disconnect, resumeAudio, notify } = useLiveKitCall(audio);

  const messages = session.transcript.map(toChatMessage);

  const handleClinicReset = async () => {
    const confirmed = window.confirm(
      "Reset clinic mock sẽ xoá dữ liệu test của CẢ TEAM và nạp lại dữ liệu mẫu.\n" +
        "Chỉ bấm khi không có ai khác đang gọi. Tiếp tục?",
    );
    if (!confirmed) return;
    setResetting(true);
    try {
      const { data } = await resetClinic(config.appointmentId);
      reloadFixtures();
      const appointment = data.appointment;
      notify({
        tone: "success",
        text: appointment
          ? `Đã reset clinic · ${appointment.appointment_id ?? "?"}: ${appointment.status ?? "?"} v${String(appointment.version)}.`
          : "Đã reset clinic (không đọc lại được lịch hẹn).",
      });
    } catch (error) {
      const reason = error instanceof Error ? error.message : "không rõ lý do";
      notify({ tone: "error", text: `Reset clinic lỗi: ${reason}` });
    } finally {
      setResetting(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Gọi thử · LiveKit"
        title="Cuộc gọi trực tiếp"
        description="Nói chuyện trực tiếp với bot qua microphone: audio stream thật qua WebRTC/LiveKit."
      />

      <div className={styles.layout}>
        <div className={styles.side}>
          <Card>
            <CardHeader
              title="Cấu hình cuộc gọi"
              action={
                <Button
                  variant="danger"
                  size="sm"
                  icon={<DatabaseZap />}
                  loading={resetting}
                  // Reset giữa cuộc gọi làm worker đọc lịch hẹn đã bị thay.
                  disabled={resetting || session.phase !== "idle"}
                  onClick={() => void handleClinicReset()}
                >
                  Reset clinic
                </Button>
              }
            />
            <CardBody className={styles.config}>
              <LiveKitConfigPanel
                config={config}
                onChange={(patch) => {
                  setConfig((current) => ({ ...current, ...patch }));
                }}
                locked={session.phase !== "idle"}
                fixtures={fixtures}
                onReloadFixtures={reloadFixtures}
              />
              <Notice>
                Nhiều worker chung một project LiveKit thì cuộc gọi có thể vào worker khác.
              </Notice>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Trích xuất lượt gần nhất" />
            <CardBody>
              <ExtractionPanel
                extraction={session.extraction}
                empty={EXTRACTION_ISSUES[session.extractionIssue ?? "none"]}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Nhật ký kết nối" />
            <CardBody>
              <EventLog entries={session.log} />
            </CardBody>
          </Card>
        </div>

        <CallPanel
          className={styles.call}
          status={describeConnection(session)}
          phase={callPhase(session)}
          onStart={() => void connect(config)}
          onEnd={() => void disconnect()}
          metrics={{
            state: session.botState,
            turnLabel: "Lượt",
            turn: session.transcript.at(-1)?.turn ?? null,
            outcome: session.outcome,
          }}
          notice={session.notice}
          messages={messages}
          empty={
            <>
              Bấm <strong>Bắt đầu cuộc gọi</strong> rồi nói vào microphone: lời thoại của bạn và bot
              hiện ở đây trong lúc gọi.
            </>
          }
          footer={
            <VoiceDock
              phase={session.phase}
              botPresent={session.botPresent}
              micEnabled={session.micEnabled}
              speaking={session.speaking}
              audioBlocked={session.audioBlocked}
              onToggleMic={() => void toggleMic()}
              onResumeAudio={() => void resumeAudio()}
            />
          }
        />
      </div>

      {/* Audio của bot; LiveKit gắn track vào đây khi bot publish. */}
      <audio ref={audio} autoPlay hidden />
    </>
  );
}

/** Pha của nút gọi dùng chung với trang HTTP. */
function callPhase(session: LiveKitSession): "idle" | "connecting" | "active" {
  if (session.phase === "connecting") return "connecting";
  return isActive(session) ? "active" : "idle";
}
