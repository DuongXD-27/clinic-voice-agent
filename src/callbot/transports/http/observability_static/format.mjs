const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export function formatDuration(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "No data";
  const milliseconds = Number(value);
  if (milliseconds < 1000) return `${integer.format(milliseconds)} ms`;
  return `${number.format(milliseconds / 1000)} s`;
}

export function formatRate(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "No data";
  return `${number.format(Number(value) * 100)}%`;
}

export function formatTimestamp(value) {
  if (!value) return "No data";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "No data";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(parsed);
}

export function formatCount(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "No data";
  return integer.format(Number(value));
}

export function displayLabel(value) {
  if (value === null || value === undefined || String(value).trim() === "") return "UNSPECIFIED";
  return String(value);
}
