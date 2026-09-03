export const shortId = (value?: string | null, length = 8): string => {
  if (!value) return "—";
  return value.length > length + 4 ? `${value.slice(0, length)}…${value.slice(-4)}` : value;
};

export const money = (value?: string | number | null): string =>
  value === null || value === undefined ? "—" : `${Number(value).toFixed(6)} USDC`;

export const displayDate = (value?: string | null): string =>
  value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";

export const stateTone = (state?: string | null): "good" | "warn" | "neutral" | "bad" => {
  const value = state?.toUpperCase() ?? "";
  if (["PERMIT", "VALID", "VERIFIED", "TICKETED", "TERMINAL", "COMPLETE", "COMPLETED", "ANCHORED", "ADMITTED", "STRUCTURALLY_ADMISSIBLE"].includes(value)) return "good";
  if (["REVIEW", "LIMITED", "PENDING", "RECEIVED", "PLANNED", "ACQUIRING", "EVALUATING", "DECIDING", "DECIDED", "LOCAL_ONLY"].includes(value)) return "warn";
  if (["FAILED", "BLOCK", "REJECTED", "INVALID"].includes(value)) return "bad";
  return "neutral";
};
