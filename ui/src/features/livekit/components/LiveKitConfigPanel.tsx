import { Field, FieldGrid, Input } from "../../../components/ui/Form";
import { Segmented } from "../../../components/ui/Segmented";
import type { Direction, LiveKitConfig } from "../model/config";

const DIRECTIONS = [
  { value: "inbound", label: "Inbound · khách gọi" },
  { value: "outbound", label: "Outbound · bot gọi" },
] as const satisfies readonly { value: Direction; label: string }[];

interface Props {
  config: LiveKitConfig;
  onChange: (patch: Partial<LiveKitConfig>) => void;
  locked: boolean;
}

/** Web demo không có caller ID/PBX thật: các trường này giả lập thông tin tổng đài gửi cho bot. */
export function LiveKitConfigPanel({ config, onChange, locked }: Props) {
  return (
    <FieldGrid>
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
      {config.direction === "inbound" ? (
        <Field
          label="Số người gọi"
          htmlFor="livekit-caller"
          wide
          hint="Để trống: bot không tra được hồ sơ và chuyển máy ngay lượt đầu (đúng chính sách)."
        >
          <Input
            id="livekit-caller"
            inputMode="tel"
            value={config.callerNumber}
            disabled={locked}
            onChange={(event) => {
              onChange({ callerNumber: event.target.value });
            }}
          />
        </Field>
      ) : (
        <Field label="Appointment ID" htmlFor="livekit-appointment" wide>
          <Input
            id="livekit-appointment"
            value={config.appointmentId}
            disabled={locked}
            onChange={(event) => {
              onChange({ appointmentId: event.target.value });
            }}
          />
        </Field>
      )}
    </FieldGrid>
  );
}
