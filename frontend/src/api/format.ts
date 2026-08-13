/** Shared formatting. Centralised so a percentage is never rendered as a ratio. */

export const pct = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined || Number.isNaN(value)
    ? "n/a"
    : `${(value * 100).toFixed(digits)}%`;

export const ratio = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined || Number.isNaN(value)
    ? "n/a"
    : value.toFixed(digits);

export const money = (
  value: number | null | undefined,
  currency: string,
): string =>
  value === null || value === undefined || Number.isNaN(value)
    ? "n/a"
    : `${currency} ${Math.round(value).toLocaleString("en-IN")}`;

export const compactMoney = (
  value: number | null | undefined,
  currency: string,
): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${currency} ${(value / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${currency} ${(value / 1e5).toFixed(2)}L`;
  return money(value, currency);
};

export const date = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { dateStyle: "medium" }) : "n/a";
