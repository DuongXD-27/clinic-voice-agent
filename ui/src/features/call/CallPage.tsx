import { DatabaseZap } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { CallPanel } from "../../components/chat/CallPanel";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { useRecorder } from "../../lib/audio/useRecorder";
import { resetClinic } from "./api";
import styles from "./CallPage.module.css";
import { Composer } from "./components/Composer";
import { ConfigPanel } from "./components/ConfigPanel";
import { DebugPanel } from "./components/DebugPanel";
import { ExtractionPanel } from "./components/ExtractionPanel";
import { ScenarioGuide } from "./components/ScenarioGuide";
import { callPhase, canSend, describeCall, isBusy, isConfigLocked } from "./model/callMachine";
import {
  DEFAULT_APPOINTMENT,
  defaultConfig,
  newCallId,
  type CallConfig,
  type Direction,
} from "./model/config";
import { PRESETS, SCENARIOS, slotOutsideWindow } from "./model/scenarios";
import { SILENCE_MS, useCallSession, type TurnInput } from "./useCallSession";
import { useClinicFixtures } from "./useClinicFixtures";

export function CallPage() {
  const [config, setConfig] = useState(() => defaultConfig());
  const [text, setText] = useState("");
  const [resetting, setResetting] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const { session, start, send, reset, hangup, notify } = useCallSession();
  const { fixtures, reload: reloadFixtures } = useClinicFixtures();
  const recorder = useRecorder();

  const locked = isConfigLocked(session);
  const active = canSend(session);
  const lastMessage = session.messages.at(-1);
  const autoPlayId = lastMessage?.role === "bot" && lastMessage.audioUrl ? lastMessage.id : null;

  const updateConfig = (patch: Partial<CallConfig>) => {
    setConfig((current) => ({ ...current, ...patch }));
  };

  const handleStart = () => {
    // Call ID cũ không mở được cuộc mới: bot trả 409 CALL_ENDED (bot đã kết thúc) hoặc phát lại
    // câu chào đã lưu (vừa bấm Kết thúc, phiên trên bot còn sống). Tự sinh ID mới.
    const next =
      session.callId !== null && config.callId.trim() === session.callId
        ? { ...config, callId: newCallId() }
        : config;
    setConfig(next);
    recorder.clear();
    setText("");
    void start(next);
  };

  const newSession = () => {
    reset();
    recorder.clear();
    setText("");
    updateConfig({ callId: newCallId() });
  };

  const sendTurn = async (input: TurnInput) => {
    const result = await send(input, { callId: config.callId.trim(), turn: session.nextTurn });
    if (!result) return;
    if (input.kind === "text") setText("");
    if (input.kind === "audio") recorder.clear();
    // Trạng thái lịch vừa đổi (CONFIRMED, BOOKED…): cập nhật dropdown.
    if (result.ended) reloadFixtures();
  };

  const handleSend = () => {
    if (config.mode === "text") {
      void sendTurn({ kind: "text", text: text.trim() });
    } else if (recorder.state.status === "ready") {
      void sendTurn({ kind: "audio", wav: recorder.state.blob });
    }
  };

  const handleSilence = () => {
    if (!active) {
      notify({ tone: "error", text: "Bấm Bắt đầu cuộc gọi trước, rồi mới gửi lượt." });
      return;
    }
    void sendTurn({ kind: "silence" });
  };

  const handleRecordToggle = async () => {
    if (recorder.state.status === "recording") {
      await recorder.stop();
      return;
    }
    try {
      await recorder.start();
    } catch (error) {
      const reason = error instanceof Error ? error.message : "không rõ lý do";
      notify({ tone: "error", text: `Không mở được microphone: ${reason}` });
    }
  };

  const handlePreset = (direction: Direction) => {
    if (locked) {
      notify({ tone: "error", text: "Đang có cuộc gọi — bấm Kết thúc trước khi đổi cấu hình." });
      return;
    }
    updateConfig({ direction, mode: "text", ...PRESETS[direction] });
    notify({ tone: "info", text: `Đã điền cấu hình ${direction}. Bấm Bắt đầu cuộc gọi.` });
  };

  const handleSay = (line: string) => {
    if (!active) {
      notify({ tone: "error", text: "Bấm Bắt đầu cuộc gọi trước, rồi chọn câu mẫu." });
    } else if (config.mode === "audio") {
      notify({ tone: "info", text: `Đang ở chế độ ghi âm — hãy đọc: “${line}”.` });
    } else {
      setText(line);
      textRef.current?.focus();
    }
  };

  const handleClinicReset = async () => {
    const confirmed = window.confirm(
      "Reset clinic mock sẽ xoá dữ liệu test của CẢ TEAM và nạp lại dữ liệu mẫu.\n" +
        "Chỉ bấm khi không có ai khác đang gọi. Tiếp tục?",
    );
    if (!confirmed) return;
    setResetting(true);
    try {
      const { data } = await resetClinic(config.appointmentId || DEFAULT_APPOINTMENT);
      // Call ID cũ sẽ phát lại câu chào đã lưu, nên reset clinic luôn đi kèm phiên mới.
      newSession();
      reloadFixtures();
      const appointment = data.appointment;
      notify({
        tone: "success",
        text: appointment
          ? `Đã reset clinic · ${appointment.appointment_id ?? "?"}: ${appointment.status ?? "?"} v${String(appointment.version)}. Đã tạo Call ID mới.`
          : "Đã reset clinic (không đọc lại được lịch hẹn). Đã tạo Call ID mới.",
      });
    } catch (error) {
      const reason = error instanceof Error ? error.message : "không rõ lý do";
      notify({ tone: "error", text: `Reset clinic lỗi: ${reason}` });
    } finally {
      setResetting(false);
    }
  };

  const handleAutoplayBlocked = useCallback(() => {
    notify({ tone: "info", text: "Trình duyệt chặn tự phát audio — bấm play trên câu của bot." });
  }, [notify]);

  return (
    <>
      <PageHeader
        eyebrow="Gọi thử · HTTP"
        title="Cuộc gọi từng lượt (Text/Audio)"
        description="Mô phỏng cuộc gọi qua hai endpoint contract: gõ lời người gọi, hoặc ghi âm từ microphone."
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
                  onClick={() => void handleClinicReset()}
                >
                  Reset clinic
                </Button>
              }
            />
            <CardBody>
              <ConfigPanel
                config={config}
                onChange={updateConfig}
                locked={locked}
                fixtures={fixtures}
                onReloadFixtures={reloadFixtures}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Trích xuất lượt gần nhất" />
            <CardBody>
              <ExtractionPanel extraction={session.extraction} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Request / response gần nhất" />
            <CardBody>
              <DebugPanel exchange={session.exchange} />
            </CardBody>
          </Card>
        </div>

        <CallPanel
          className={styles.call}
          status={describeCall(session)}
          phase={callPhase(session)}
          onStart={handleStart}
          onEnd={hangup}
          metrics={{
            state: session.botState,
            turnLabel: "Lượt tiếp theo",
            turn: session.nextTurn,
            outcome: session.outcome,
          }}
          notice={session.notice}
          messages={session.messages}
          empty={
            <>
              Bấm <strong>Bắt đầu cuộc gọi</strong>: bot chào ở lượt 0, sau đó gõ hoặc ghi âm từng
              lượt của người gọi.
            </>
          }
          pending={isBusy(session)}
          autoPlayId={autoPlayId}
          onAutoplayBlocked={handleAutoplayBlocked}
          footer={
            <Composer
              mode={config.mode}
              enabled={active}
              busy={session.phase === "sending"}
              text={text}
              onTextChange={setText}
              textRef={textRef}
              recorder={recorder.state}
              onRecordToggle={() => void handleRecordToggle()}
              onSend={handleSend}
              onSilence={handleSilence}
              silenceSeconds={SILENCE_MS / 1000}
            />
          }
        />
      </div>

      <section className={styles.guide} aria-labelledby="guide-heading">
        <h2 id="guide-heading" className={styles.sectionTitle}>
          Kịch bản mẫu
        </h2>
        <ScenarioGuide
          scenarios={SCENARIOS}
          slotOutsideWindow={slotOutsideWindow()}
          onPreset={handlePreset}
          onSay={handleSay}
          onSilence={handleSilence}
        />
      </section>
    </>
  );
}
