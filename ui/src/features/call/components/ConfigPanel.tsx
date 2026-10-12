import { RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "../../../components/ui/Button";
import { Field, FieldGrid, Input, Select } from "../../../components/ui/Form";
import { Segmented } from "../../../components/ui/Segmented";
import type { CallConfig, Direction, Mode } from "../model/config";
import {
  appointmentOptions,
  fixturesHint,
  phoneOptions,
  type FixturesState,
} from "../model/fixtures";
import { CallerPhoneSelect } from "./CallerPhoneSelect";
import styles from "./ConfigPanel.module.css";

const DIRECTIONS = [
  { value: "outbound", label: "Outbound · bot gọi" },
  { value: "inbound", label: "Inbound · khách gọi" },
] as const satisfies readonly { value: Direction; label: string }[];

const MODES = [
  { value: "text", label: "Văn bản" },
  { value: "audio", label: "Ghi âm từng lượt" },
] as const satisfies readonly { value: Mode; label: string }[];

interface Props {
  config: CallConfig;
  onChange: (patch: Partial<CallConfig>) => void;
  /** Khoá khi cuộc gọi đang mở: đổi cấu hình giữa chừng làm lệch session. */
  locked: boolean;
  apiKey: string;
  onApiKeyChange: (value: string) => void;
  /** Rời ô API key: lưu vào tab và tải lại dữ liệu clinic bằng key mới. */
  onApiKeyCommit: () => void;
  apiKeyInvalid: boolean;
  fixtures: FixturesState;
  onReloadFixtures: () => void;
}

export function ConfigPanel({
  config,
  onChange,
  locked,
  apiKey,
  onApiKeyChange,
  onApiKeyCommit,
  apiKeyInvalid,
  fixtures,
  onReloadFixtures,
}: Props) {
  const apiKeyRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (apiKeyInvalid) apiKeyRef.current?.focus();
  }, [apiKeyInvalid]);

  return (
    <FieldGrid>
      <Field
        label="API key"
        htmlFor="api-key"
        wide
        hint="Bearer key của bot, để trống nếu bot tắt auth. Chỉ lưu trong tab này."
        error={apiKeyInvalid ? "API key không hợp lệ hoặc còn thiếu." : null}
      >
        <Input
          id="api-key"
          ref={apiKeyRef}
          type="password"
          autoComplete="off"
          placeholder="sk_…"
          value={apiKey}
          invalid={apiKeyInvalid}
          onChange={(event) => {
            onApiKeyChange(event.target.value);
          }}
          onBlur={onApiKeyCommit}
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

      <Field label="Hướng gọi" wide>
        <Segmented
          label="Hướng gọi"
          name="direction"
          value={config.direction}
          options={DIRECTIONS}
          disabled={locked}
          onChange={(direction) => {
            onChange({ direction });
          }}
        />
      </Field>

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

      {config.direction === "outbound" ? (
        <Field label="Appointment ID" htmlFor="appointment-id" wide>
          <Select
            id="appointment-id"
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
      ) : (
        <Field label="Số người gọi" htmlFor="caller-select" wide>
          <CallerPhoneSelect
            id="caller-select"
            value={config.callerNumber}
            phones={phoneOptions(fixtures)}
            disabled={locked}
            onChange={(callerNumber) => {
              onChange({ callerNumber });
            }}
          />
        </Field>
      )}

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
