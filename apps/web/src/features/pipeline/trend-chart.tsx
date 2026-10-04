import type { TrendPoint } from "@/lib/api/types";
import { formatDropKey, formatInt, formatScore } from "@/lib/format";

/**
 * Recent runs: bar height = rows read, bar colour = outcome, dot = data-quality score.
 * Plain SVG (no charting library) to keep the page light.
 */
export function TrendChart({ points }: { points: TrendPoint[] }) {
  if (points.length === 0) return null;
  const width = 640;
  const height = 140;
  const pad = { top: 10, right: 8, bottom: 18, left: 8 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const maxRows = Math.max(1, ...points.map((p) => p.rows_read));
  const slot = innerW / Math.max(points.length, 12);
  const barW = Math.max(3, slot * 0.6);
  const y = (score: number) => pad.top + innerH * (1 - score / 100);

  return (
    <figure>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Last ${points.length} runs: rows read per run and data-quality score`}
      >
        {[0, 50, 100].map((v) => (
          <line
            key={v}
            x1={pad.left}
            x2={width - pad.right}
            y1={y(v)}
            y2={y(v)}
            stroke="var(--color-line)"
            strokeDasharray={v === 0 ? undefined : "2 4"}
          />
        ))}
        {points.map((p, i) => {
          const x = pad.left + i * slot + (slot - barW) / 2;
          const h = Math.max(2, (p.rows_read / maxRows) * innerH);
          const color =
            p.status === "failed"
              ? "var(--color-fail)"
              : "color-mix(in srgb, var(--color-muted) 55%, transparent)";
          return (
            <g key={p.id}>
              <title>
                {`${formatDropKey(p.drop_key)}: ${p.status}, ${formatInt(p.rows_read)} rows, quality ${formatScore(p.dq_score)}`}
              </title>
              <rect x={x} y={pad.top + innerH - h} width={barW} height={h} rx={1.5} fill={color} />
              {p.dq_score !== null && p.dq_score !== undefined && (
                <circle cx={x + barW / 2} cy={y(p.dq_score)} r={2.6} fill="var(--color-pass)" />
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
        <span>Bars: rows read per run, oldest first (red if the run failed)</span>
        <span className="text-pass">Dots: quality score, 0 to 100</span>
      </figcaption>
    </figure>
  );
}
