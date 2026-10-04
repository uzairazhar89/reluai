/**
 * The pipeline's architecture as an HTML flow (readable by screen readers, reflows on
 * phones). Stages read left to right on wide screens and top to bottom on narrow ones.
 */
const sources = [
  ["Monthly CSV drops", "25 files, original export layout"],
  ["Product catalogue", "JSON master data"],
  ["CRM REST API", "paginated, can fail"],
];

const stages = [
  ["Extract", "Retries with backoff and jitter; structural errors caught per line"],
  ["Validate", "Data contract, business and integrity rules with reason codes, de-duplication"],
  ["Transform", "Normalise codes and text, classify lines, stable line keys"],
  ["Quality gate", "Batch checks; a failed gate stops the run before any write"],
  ["Load", "COPY + upserts in one transaction, reconciliation check"],
];

function Arrow() {
  return (
    <span aria-hidden className="flex items-center justify-center text-faint">
      <svg viewBox="0 0 16 16" className="size-4 rotate-90 md:rotate-0" fill="none">
        <path d="M2 8h11M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </span>
  );
}

export function PipelineArchitecture() {
  return (
    <figure className="rounded-md border border-line bg-surface p-5 text-sm">
      <div className="grid gap-3 md:grid-cols-[auto_auto_1fr] md:items-center">
        <ul className="space-y-2" aria-label="Sources">
          {sources.map(([name, note]) => (
            <li key={name} className="rounded-sm border border-line-strong px-3 py-2">
              <p className="font-medium text-text">{name}</p>
              <p className="text-xs text-muted">{note}</p>
            </li>
          ))}
        </ul>
        <Arrow />
        <ol
          className="grid gap-2 md:grid-cols-[repeat(5,minmax(0,1fr))] md:gap-1.5"
          aria-label="Pipeline stages"
        >
          {stages.map(([name, note], i) => (
            <li key={name} className="relative rounded-sm bg-surface-2 px-3 py-2.5">
              <p className="font-medium text-text">
                <span className="num mr-1.5 text-faint">{i + 1}</span>
                {name}
              </p>
              <p className="mt-1 text-xs text-muted">{note}</p>
            </li>
          ))}
        </ol>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-sm border border-warn/40 px-3 py-2">
          <p className="font-medium text-warn">Quarantine</p>
          <p className="text-xs text-muted">
            Every rejected row kept with its line number and reason code
          </p>
        </div>
        <div className="rounded-sm border border-pass/40 px-3 py-2">
          <p className="font-medium text-pass">PostgreSQL warehouse</p>
          <p className="text-xs text-muted">
            retail.invoice, invoice_line, customer, product; read by later projects
          </p>
        </div>
        <div className="rounded-sm border border-line-strong px-3 py-2">
          <p className="font-medium text-text">Run metadata</p>
          <p className="text-xs text-muted">
            Steps, real log lines, data-quality results, environment
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 border-t border-line pt-4 md:grid-cols-3">
        <p className="text-xs text-muted">
          <span className="font-medium text-text">Triggers.</span> A schedule every 6 hours,
          visitors (rate-limited), or the CLI.
        </p>
        <p className="text-xs text-muted">
          <span className="font-medium text-text">Execution.</span> A PostgreSQL job queue and a
          global CPU lease, so one heavy job runs at a time on 2 vCPUs.
        </p>
        <p className="text-xs text-muted">
          <span className="font-medium text-text">Read side.</span> A FastAPI service feeds the
          dashboard below; nginx in front limits request rates.
        </p>
      </div>
      <figcaption className="sr-only">
        Three sources feed five stages: extract, validate, transform, quality gate and load.
        Rejected rows go to quarantine, published rows to the PostgreSQL warehouse, and every run
        records its metadata.
      </figcaption>
    </figure>
  );
}
