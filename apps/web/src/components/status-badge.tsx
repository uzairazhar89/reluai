type Tone = "pass" | "warn" | "fail" | "neutral";

const tones: Record<Tone, string> = {
  pass: "text-pass bg-pass/10 ring-pass/30",
  warn: "text-warn bg-warn/10 ring-warn/30",
  fail: "text-fail bg-fail/10 ring-fail/30",
  neutral: "text-muted bg-surface-2 ring-line",
};

const runTone: Record<string, Tone> = {
  succeeded: "pass",
  failed: "fail",
  running: "warn",
  queued: "neutral",
  operational: "pass",
  degraded: "warn",
  down: "fail",
};

const runLabel: Record<string, string> = {
  succeeded: "Succeeded",
  failed: "Failed",
  running: "Running",
  queued: "Queued",
  operational: "Operational",
  degraded: "Degraded",
  down: "Down",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const tone = runTone[status] ?? "neutral";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {label ?? runLabel[status] ?? status}
    </span>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-sm px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
