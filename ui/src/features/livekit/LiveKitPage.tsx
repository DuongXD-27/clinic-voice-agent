import { Mic, MicOff, PhoneCall, PhoneOff, Volume2 } from "lucide-react";
import { useRef, useState } from "react";

import { CallStatus } from "../../components/chat/CallStatus";
import { Conversation } from "../../components/chat/Conversation";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { Notice } from "../../components/ui/Notice";
import { StatusIndicator } from "../../components/ui/StatusIndicator";
import { EventLog } from "./components/EventLog";
import { LiveKitConfigPanel } from "./components/LiveKitConfigPanel";
import { Participants } from "./components/Participants";
import styles from "./LiveKitPage.module.css";
import { DEFAULT_LIVEKIT_CONFIG, type LiveKitConfig } from "./model/config";
import { describeConnection, isActive } from "./model/session";
import { toChatMessage } from "./model/transcript";
import { useLiveKitCall } from "./useLiveKitCall";

export function LiveKitPage() {
  const [config, setConfig] = useState<LiveKitConfig>(DEFAULT_LIVEKIT_CONFIG);
  const audio = useRef<HTMLAudioElement>(null);
  const { session, connect, toggleMic, disconnect, resumeAudio } = useLiveKitCall(audio);

  const active = isActive(session);
  const connecting = session.phase === "connecting";
  const messages = session.transcript.map(toChatMessage);

  return (
    <>
      <PageHeader
        eyebrow="Gọi thử · LiveKit"
        title="Cuộc gọi giọng nói"
        description="Nói chuyện trực tiếp với bot qua microphone: audio stream thật qua WebRTC/LiveKit, không ghi âm rồi upload."
      />

      <div className={styles.layout}>
        <div className={styles.side}>
          <Card>
            <CardHeader title="Cấu hình cuộc gọi" />
            <CardBody className={styles.config}>
              <LiveKitConfigPanel
                config={config}
                onChange={(patch) => {
                  setConfig((current) => ({ ...current, ...patch }));
                }}
                locked={session.phase !== "idle"}
              />
              <Notice>
                Trình duyệt sẽ xin quyền microphone khi bắt đầu. Bot trả lời do LiveKit worker xử
                lý: nếu nhiều worker cùng đăng ký một project LiveKit, cuộc gọi có thể vào worker
                khác.
              </Notice>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Nhật ký kết nối" />
            <CardBody>
              <EventLog entries={session.log} />
            </CardBody>
          </Card>
        </div>

        <Card className={styles.call}>
          <div className={styles.toolbar}>
            <div role="status" aria-label="Trạng thái kết nối">
              <StatusIndicator {...describeConnection(session)} />
            </div>
            <div className={styles.actions}>
              {session.audioBlocked && (
                <Button icon={<Volume2 />} onClick={() => void resumeAudio()}>
                  Bật âm thanh
                </Button>
              )}
              {active ? (
                <>
                  <Button
                    icon={session.micEnabled ? <MicOff /> : <Mic />}
                    onClick={() => void toggleMic()}
                  >
                    {session.micEnabled ? "Tắt mic" : "Bật mic"}
                  </Button>
                  <Button variant="danger" icon={<PhoneOff />} onClick={() => void disconnect()}>
                    Kết thúc
                  </Button>
                </>
              ) : (
                <Button
                  variant="primary"
                  icon={<PhoneCall />}
                  loading={connecting}
                  onClick={() => void connect(config)}
                >
                  Bắt đầu cuộc gọi
                </Button>
              )}
            </div>
          </div>
          {session.notice && (
            <div className={styles.notice}>
              <Notice tone={session.notice.tone}>{session.notice.text}</Notice>
            </div>
          )}
          <Participants
            phase={session.phase}
            botPresent={session.botPresent}
            micEnabled={session.micEnabled}
            speaking={session.speaking}
          />
          <CallStatus
            state={session.botState}
            turnLabel="Lượt"
            turn={session.transcript.at(-1)?.turn ?? null}
            outcome={session.outcome}
          />
          <Conversation
            messages={messages}
            empty="Lời thoại của bạn và bot sẽ hiện ở đây trong lúc gọi."
          />
        </Card>
      </div>

      {/* Audio của bot; LiveKit gắn track vào đây khi bot publish. */}
      <audio ref={audio} autoPlay hidden />
    </>
  );
}
