import { RefreshCw } from "lucide-react";

import { Button } from "../../../components/ui/Button";
import { Field, FieldGrid, Input, Select } from "../../../components/ui/Form";
import { Segmented } from "../../../components/ui/Segmented";
import { CallerPhoneSelect } from "../../call/components/CallerPhoneSelect";
import {
  appointmentOptions,
  fixturesHint,
  phoneOptions,
  type FixturesState,
} from "../../call/model/fixtures";
import type { AsrChoice, Direction, LiveKitConfig } from "../model/config";
import styles from "./LiveKitConfigPanel.module.css";

const DIRECTIONS = [
  { value: "inbound", label: "Inbound · khách gọi" },
  { value: "outbound", label: "Outbound · bot gọi" },
] as const satisfies readonly { value: Direction; label: string }[];

const ASR_CHOICES = [
  { value: "server", label: "Theo server" },
  { value: "zipformer", label: "GipFormer" },
  { value: "gemini_live", label: "Gemini Live" },
] as const satisfies readonly { value: AsrChoice; label: string }[];

interface Props {
  config: LiveKitConfig;
  onChange: (patch: Partial<LiveKitConfig>) => void;
  locked: boolean;
  apiKey: string;
  onApiKeyChange: (value: string) => void;
  /** Rời ô API key: lưu vào tab và tải lại dữ liệu clinic bằng key mới. */
  onApiKeyCommit: () => void;
  fixtures: FixturesState;
  onReloadFixtures: () => void;
}

/** Web demo không có caller ID/PBX thật: các trường này giả lập thông tin tổng đài gửi cho bot. */
export function LiveKitConfigPanel({
  config,
  onChange,
  locked,
  apiKey,
  onApiKeyChange,
  onApiKeyCommit,
  fixtures,
  onReloadFixtures,
}: Props) {
  return (
    <FieldGrid>
      <Field
        label="API key"
        htmlFor="livekit-api-key"
        wide
        hint="Bearer key của bot, chỉ để tải danh sách lịch hẹn. Dùng chung với trang gọi HTTP."
      >
        <Input
          id="livekit-api-key"
          type="password"
          autoComplete="off"
          placeholder="sk_…"
          value={apiKey}
          onChange={(event) => {
            onApiKeyChange(event.target.value);
          }}
          onBlur={onApiKeyCommit}
        />
      </Field>
      <Field label="Hướng gọi (giả lập)" wide>
        <Segmented
          label="Hướng gọi"
          name="livekit-direction"
          value={config.direction}
          options={DIRECTIONS}
          disabled={locked}
          onChange={(direction) => {
            onChange({ direction });
          }}
        />
      </Field>
      <Field
        label="Nhận dạng giọng (ASR)"
        wide
        hint="Áp cho cuộc gọi kế tiếp. Theo server: dùng LIVEKIT_ASR_PROVIDER/ASR_PROVIDER của worker."
      >
        <Segmented
          label="Nhận dạng giọng"
          name="livekit-asr"
          value={config.asrProvider}
          options={ASR_CHOICES}
          disabled={locked}
          onChange={(asrProvider) => {
            onChange({ asrProvider });
          }}
        />
      </Field>
      {config.direction === "inbound" ? (
        <Field
          label="Số người gọi"
          htmlFor="livekit-caller"
          wide
          hint="Nhập số khác rồi để trống: bot không tra được hồ sơ và chuyển máy ngay lượt đầu (đúng chính sách)."
        >
          <CallerPhoneSelect
            id="livekit-caller"
            value={config.callerNumber}
            phones={phoneOptions(fixtures)}
            disabled={locked}
            onChange={(callerNumber) => {
              onChange({ callerNumber });
            }}
          />
        </Field>
      ) : (
        <Field label="Appointment ID" htmlFor="livekit-appointment" wide>
          <Select
            id="livekit-appointment"
            value={config.appointmentId}
            disabled={locked}
            onChange={(event) => {
              onChange({ appointmentId: event.target.value });
            }}
          >
            {appointmentOptions(fixtures, config.appointmentId).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <div className={styles.fixtures}>
        <span>{fixturesHint(fixtures)}</span>
        <Button
          variant="ghost"
          size="sm"
          icon={<RefreshCw />}
          loading={fixtures.status === "loading"}
          onClick={onReloadFixtures}
        >
          Tải lại
        </Button>
      </div>
    </FieldGrid>
  );
}
