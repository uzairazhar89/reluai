import { formatDuration } from "@/lib/format";

export interface StepTiming {
  name: string;
  status: string;
  duration_ms: number;
}

const label: Record<string, string> = {
  resolve: "Resolve",
  extract: "Extract",
  validate: "Validate",
  transform: "Transform",
  quality_gate: "Quality gate",
  load: "Load",
};

const fill: Record<string, string> = {
  succeeded: "bg-muted/70",
  failed: "bg-fail",
  skipped: "border border-dashed border-line-strong bg-transparent",
};

/**
 * A run's steps as one horizontal bar, each segment as wide as its share of the run time.
 * `animate` plays a single left-to-right reveal (the hero's only motion); reduced-motion
 * users see the finished bar.
 */
export function StepBar({ steps, animate = false }: { steps: StepTiming[]; animate?: boolean }) {
  const total = Math.max(
    1,
    steps.reduce((s, x) => s + x.duration_ms, 0),
  );
  return (
    <figure>
      <div
        className="flex h-2.5 w-full gap-[3px] overflow-hidden rounded-sm"
        role="img"
        aria-label={steps
          .map((s) => `${label[s.name] ?? s.name} ${formatDuration(s.duration_ms)}`)
          .join(", ")}
      >
        {steps.map((s, i) => (
          <span
            key={`${s.name}-${i}`}
            className={`block h-full rounded-[2px] ${fill[s.status] ?? "bg-muted/70"} ${animate ? "origin-left animate-[grow_600ms_ease-out_both]" : ""}`}
            style={{
              width: `${Math.max(2, (s.duration_ms / total) * 100)}%`,
              animationDelay: animate ? `${i * 90}ms` : undefined,
            }}
          />
        ))}
      </div>
      <figcaption className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted">
        {steps.map((s, i) => (
          <span key={`${s.name}-${i}`} className="flex justify-between gap-3">
            <span className={s.status === "failed" ? "text-fail" : undefined}>
              {label[s.name] ?? s.name}
              {s.status === "skipped" ? " (skipped)" : ""}
            </span>
            <span className="num text-faint">{formatDuration(s.duration_ms)}</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
