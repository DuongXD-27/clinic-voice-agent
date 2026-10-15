import { Field, FieldGrid, Input } from "../../../components/ui/Form";
import { Segmented } from "../../../components/ui/Segmented";
import type { CallConfig, Mode } from "../model/config";
import type { FixturesState } from "../model/fixtures";
import { CallTargetFields } from "./CallTargetFields";

const MODES = [
  { value: "text", label: "Văn bản" },
  { value: "audio", label: "Ghi âm từng lượt" },
] as const satisfies readonly { value: Mode; label: string }[];

interface Props {
  config: CallConfig;
  onChange: (patch: Partial<CallConfig>) => void;
  /** Khoá khi cuộc gọi đang mở: đổi cấu hình giữa chừng làm lệch session. */
  locked: boolean;
  fixtures: FixturesState;
  onReloadFixtures: () => void;
}

export function ConfigPanel({ config, onChange, locked, fixtures, onReloadFixtures }: Props) {
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
      />

      <Field label="Chế độ" wide>
        <Segmented
          label="Chế độ"
          name="mode"
          value={config.mode}
          options={MODES}
          disabled={locked}
          onChange={(mode) => {
            onChange({ mode });
          }}
        />
      </Field>

      <Field label="Call ID" htmlFor="call-id" wide>
        <Input
          id="call-id"
          value={config.callId}
          maxLength={128}
          disabled={locked}
          onChange={(event) => {
            onChange({ callId: event.target.value });
          }}
        />
      </Field>

      <Field label="Locale" htmlFor="locale">
        <Input
          id="locale"
          value={config.locale}
          disabled={locked}
          onChange={(event) => {
            onChange({ locale: event.target.value });
          }}
        />
      </Field>

      <Field label="Max turns" htmlFor="max-turns">
        <Input
          id="max-turns"
          type="number"
          min={1}
          // Ô trống cho valueAsNumber = NaN: hiện rỗng, validateConfig chặn lúc bắt đầu.
          value={Number.isNaN(config.maxTurns) ? "" : config.maxTurns}
          disabled={locked}
          onChange={(event) => {
            onChange({ maxTurns: event.target.valueAsNumber });
          }}
        />
      </Field>
    </FieldGrid>
  );
}
