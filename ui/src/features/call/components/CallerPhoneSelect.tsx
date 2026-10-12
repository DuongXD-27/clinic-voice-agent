import { Input, Select } from "../../../components/ui/Form";
import type { Option } from "../model/fixtures";

const MANUAL_PHONE = "__manual__";

interface Props {
  id: string;
  value: string;
  /** Số điện thoại từ dữ liệu clinic (`phoneOptions`); rỗng khi chưa tải hoặc tải lỗi. */
  phones: readonly Option[];
  disabled: boolean;
  onChange: (callerNumber: string) => void;
}

/**
 * Số người gọi inbound: chọn từ dữ liệu clinic, hoặc "Nhập số khác…" để gõ tay (kể cả để trống).
 * Số không có trong danh sách (fixtures chưa tải, số gõ tay) tự hiện ô nhập.
 */
export function CallerPhoneSelect({ id, value, phones, disabled, onChange }: Props) {
  const manual = !phones.some((option) => option.value === value);
  return (
    <>
      <Select
        id={id}
        value={manual ? MANUAL_PHONE : value}
        disabled={disabled}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === MANUAL_PHONE ? "" : next);
        }}
      >
        {phones.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
        <option value={MANUAL_PHONE}>Nhập số khác…</option>
      </Select>
      {manual && (
        <Input
          aria-label="Số điện thoại người gọi"
          inputMode="tel"
          placeholder="Ví dụ 0912345600"
          value={value}
          disabled={disabled}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </>
  );
}
