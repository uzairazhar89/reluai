import type { AskResponse, ResultColumn } from "@/lib/api/types";

import { formatCell, type Grain } from "./format";

interface Props {
  answer: AskResponse;
}

const asNumber = (v: unknown): number | null => (typeof v === "number" ? v : null);

function BigNumber({ column, value }: { column: ResultColumn; value: unknown }) {
  return (
    <figure className="py-4">
      <p className="num display text-[2.4rem] leading-none text-text sm:text-[3rem]">
        {formatCell(value, column)}
      </p>
      <figcaption className="mt-3 text-sm text-muted">{column.label}</figcaption>
    </figure>
  );
}

/** Horizontal bars: long category names stay readable on a phone. */
function Bars({
  label,
  metric,
  rows,
  grain,
}: {
  label: ResultColumn;
  metric: ResultColumn;
  rows: unknown[][];
  grain: Grain | null;
}) {
  const li = 0;
  const mi = 1;
  const values = rows.map((r) => asNumber(r[mi]) ?? 0);
  const max = Math.max(1e-9, ...values.map(Math.abs));
  return (
    <figure>
      <figcaption className="mb-3 text-sm text-muted">
        {metric.label} by {label.label.toLowerCase()}
      </figcaption>
      <ol className="space-y-1.5">
        {rows.map((r, i) => {
          const v = values[i] ?? 0;
          const pct = (Math.abs(v) / max) * 100;
          return (
            <li
              key={i}
              className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] items-center gap-3 text-sm sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]"
            >
              <span className="truncate text-text" title={formatCell(r[li], label, grain)}>
                {formatCell(r[li], label, grain)}
              </span>
              <span className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden
                  className={`h-3 shrink-0 rounded-[2px] ${v < 0 ? "bg-fail/70" : "bg-link/70"}`}
                  style={{ width: `${Math.max(pct, 0.6)}%`, maxWidth: "calc(100% - 6rem)" }}
                />
                <span className="num shrink-0 text-muted">{formatCell(r[mi], metric)}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </figure>
  );
}

function Line({
  time,
  metric,
  rows,
  grain,
}: {
  time: ResultColumn;
  metric: ResultColumn;
  rows: unknown[][];
  grain: Grain | null;
}) {
  const width = 640;
  const height = 220;
  const pad = { top: 16, right: 12, bottom: 28, left: 12 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const values = rows.map((r) => asNumber(r[1]));
  const finite = values.filter((v): v is number => v !== null);
  const hi = Math.max(0, ...finite);
  const lo = Math.min(0, ...finite);
  const span = hi - lo || 1;
  const x = (i: number) =>
    pad.left + (rows.length === 1 ? innerW / 2 : (i / (rows.length - 1)) * innerW);
  const y = (v: number) => pad.top + innerH * (1 - (v - lo) / span);
  const points = values
    .map((v, i) => (v === null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`))
    .filter(Boolean)
    .join(" ");
  const peak = finite.length ? values.indexOf(Math.max(...finite)) : -1;
  const first = rows[0]?.[0];
  const last = rows[rows.length - 1]?.[0];

  return (
    <figure>
      <figcaption className="mb-2 text-sm text-muted">
        {metric.label} by {time.label.toLowerCase()}
        {peak >= 0 && (
          <>
            {"; highest: "}
            <span className="text-text">
              {formatCell(rows[peak]?.[0], time, grain)}, {formatCell(values[peak], metric)}
            </span>
          </>
        )}
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label={`${metric.label} by ${time.label.toLowerCase()}, ${rows.length} points from ${formatCell(first, time, grain)} to ${formatCell(last, time, grain)}`}
      >
        <line
          x1={pad.left}
          x2={width - pad.right}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--color-line-strong)"
        />
        <line
          x1={pad.left}
          x2={width - pad.right}
          y1={y(hi)}
          y2={y(hi)}
          stroke="var(--color-line)"
          strokeDasharray="2 4"
        />
        <polyline
          points={points}
          fill="none"
          stroke="var(--color-link)"
          strokeWidth={2}
          strokeLinejoin="round"
        />
        {values.map((v, i) =>
          v === null ? null : (
            <circle
              key={i}
              cx={x(i)}
              cy={y(v)}
              r={rows.length > 40 ? 1.6 : 2.6}
              fill="var(--color-link)"
            >
              <title>{`${formatCell(rows[i]?.[0], time, grain)}: ${formatCell(v, metric)}`}</title>
            </circle>
          ),
        )}
        <text x={pad.left} y={height - 8} fontSize={12} fill="var(--color-muted)">
          {formatCell(first, time, grain)}
        </text>
        <text
          x={width - pad.right}
          y={height - 8}
          fontSize={12}
          fill="var(--color-muted)"
          textAnchor="end"
        >
          {formatCell(last, time, grain)}
        </text>
        <text
          x={width - pad.right}
          y={y(hi) - 5}
          fontSize={12}
          fill="var(--color-muted)"
          textAnchor="end"
        >
          {formatCell(hi, metric)}
        </text>
      </svg>
    </figure>
  );
}

/** The chart the API chose for the result's shape; anything else is best read as a table. */
export function ResultChart({ answer }: Props) {
  const columns = answer.columns ?? [];
  const rows = answer.rows ?? [];
  const grain = (answer.plan?.time_bucket?.grain ?? null) as Grain | null;
  if (rows.length === 0)
    return <p className="text-sm text-muted">No rows matched, so there is nothing to chart.</p>;

  if (answer.chart === "number" && columns[0]) {
    return <BigNumber column={columns[0]} value={rows[0]?.[0]} />;
  }
  const [first, second] = columns;
  if (answer.chart === "line" && first?.role === "time" && second) {
    return <Line time={first} metric={second} rows={rows} grain={grain} />;
  }
  if (answer.chart === "bar" && first && second?.role === "metric") {
    return <Bars label={first} metric={second} rows={rows} grain={grain} />;
  }
  return (
    <p className="text-sm text-muted">
      This answer has more than one grouping or measure, so it reads best as a table. Use the Table
      tab.
    </p>
  );
}
