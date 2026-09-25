import { cx } from "../../lib/cx";
import styles from "./Segmented.module.css";

interface Props<T extends string> {
  /** Tên nhóm hiển thị cho trình đọc màn hình. */
  label: string;
  name: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  disabled?: boolean;
}

/** Chọn một trong vài giá trị: radio thật bên dưới nên bàn phím và trình đọc màn hình dùng được. */
export function Segmented<T extends string>({
  label,
  name,
  value,
  options,
  onChange,
  disabled = false,
}: Props<T>) {
  return (
    <div role="radiogroup" aria-label={label} className={styles.group}>
      {options.map((option) => (
        <label
          key={option.value}
          className={cx(
            styles.option,
            option.value === value && styles.selected,
            disabled && styles.disabled,
          )}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={option.value === value}
            disabled={disabled}
            onChange={() => {
              onChange(option.value);
            }}
            className="visually-hidden"
          />
          {option.label}
        </label>
      ))}
    </div>
  );
}
