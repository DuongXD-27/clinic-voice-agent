import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "../../../components/ui/Button";
import { Field, Select } from "../../../components/ui/Form";
import { Segmented } from "../../../components/ui/Segmented";
import type { Direction } from "../model/config";
import {
  appointmentOptions,
  fixturesHint,
  phoneOptions,
  type FixturesState,
} from "../model/fixtures";
import { CallerPhoneSelect } from "./CallerPhoneSelect";

const DIRECTIONS = [
  { value: "outbound", label: "Outbound · bot gọi" },
  { value: "inbound", label: "Inbound · khách gọi" },
] as const satisfies readonly { value: Direction; label: string }[];

export interface CallTarget {
  direction: Direction;
  /** outbound */
  appointmentId: string;
  /** inbound */
  callerNumber: string;
}

interface Props extends CallTarget {
  onChange: (patch: Partial<CallTarget>) => void;
  locked: boolean;
  fixtures: FixturesState;
  onReloadFixtures: () => void;
  /** Gợi ý thêm dưới ô số người gọi (luật số trống khác nhau giữa HTTP và LiveKit). */
  callerHint?: ReactNode;
}

/**
 * Hướng gọi và lịch hẹn (outbound) / số người gọi (inbound), lấy từ dữ liệu clinic. Đặt đầu form
 * cấu hình, giống hệt nhau ở trang gọi HTTP và LiveKit. Con trực tiếp của `FieldGrid`.
 */
export function CallTargetFields({
  direction,
  appointmentId,
  callerNumber,
  onChange,
  locked,
  fixtures,
  onReloadFixtures,
  callerHint,
}: Props) {
  const reload = (
    <Button
      variant="ghost"
      size="sm"
      icon={<RefreshCw />}
      loading={fixtures.status === "loading"}
      onClick={onReloadFixtures}
    >
      Tải lại
    </Button>
  );
  const source = fixturesHint(fixtures);
  return (
    <>
      <Field label="Hướng gọi" wide>
        <Segmented
          label="Hướng gọi"
          name="direction"
          value={direction}
          options={DIRECTIONS}
          disabled={locked}
          onChange={(next) => {
            onChange({ direction: next });
          }}
        />
      </Field>

      {direction === "outbound" ? (
        <Field label="Appointment ID" htmlFor="appointment-id" wide action={reload} hint={source}>
          <Select
            id="appointment-id"
            value={appointmentId}
            disabled={locked}
            onChange={(event) => {
              onChange({ appointmentId: event.target.value });
            }}
          >
            {appointmentOptions(fixtures, appointmentId).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>
      ) : (
        <Field
          label="Số người gọi"
          htmlFor="caller-select"
          wide
          action={reload}
          hint={
            callerHint ? (
              <>
                {callerHint}
                <br />
                {source}
              </>
            ) : (
              source
            )
          }
        >
          <CallerPhoneSelect
            id="caller-select"
            value={callerNumber}
            phones={phoneOptions(fixtures)}
            disabled={locked}
            onChange={(next) => {
              onChange({ callerNumber: next });
            }}
          />
        </Field>
      )}
    </>
  );
}
