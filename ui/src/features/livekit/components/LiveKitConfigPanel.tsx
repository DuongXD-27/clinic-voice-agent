import { Field, FieldGrid } from "../../../components/ui/Form";
import { Segmented } from "../../../components/ui/Segmented";
import { CallTargetFields } from "../../call/components/CallTargetFields";
import type { FixturesState } from "../../call/model/fixtures";
import type { AsrChoice, LiveKitConfig } from "../model/config";

const ASR_CHOICES = [
  { value: "server", label: "Theo server" },
  { value: "zipformer", label: "GipFormer" },
  { value: "gemini_live", label: "Gemini Live" },
] as const satisfies readonly { value: AsrChoice; label: string }[];

interface Props {
  config: LiveKitConfig;
  onChange: (patch: Partial<LiveKitConfig>) => void;
  locked: boolean;
  fixtures: FixturesState;
  onReloadFixtures: () => void;
}

/**
 * Hướng gọi và số người gọi giống trang HTTP. Web demo không có caller ID/PBX thật: các trường này
 * giả lập thông tin tổng đài gửi cho bot.
 */
export function LiveKitConfigPanel({
  config,
  onChange,
  locked,
  fixtures,
  onReloadFixtures,
}: Props) {
  return (
    <FieldGrid>
      <CallTargetFields
        direction={config.direction}
        appointmentId={config.appointmentId}
        callerNumber={config.callerNumber}
        onChange={onChange}
        locked={locked}
        fixtures={fixtures}
        onReloadFixtures={onReloadFixtures}
        callerHint="Nhập số khác rồi để trống: bot không tra được hồ sơ và chuyển máy ngay lượt đầu (đúng chính sách)."
      />
      <Field
        label="Nhận dạng giọng (ASR)"
        wide
        hint="Theo server: dùng ASR cấu hình sẵn của worker."
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
    </FieldGrid>
  );
}
