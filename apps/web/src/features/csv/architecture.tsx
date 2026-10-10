/**
 * How a question becomes an answer, as an HTML flow (readable by screen readers, reflows on
 * phones). The point it makes: whatever interprets the question, only a validated plan
 * reaches the database, and the database runs locked down.
 */
const steps = [
  ["Question", "Plain English, up to 300 characters"],
  [
    "Rule-based parser",
    "Fixed vocabulary from the table's columns and values; declines what it cannot read",
  ],
  ["Query plan", "Data, not code: measures, groupings, filters, sort, limit"],
  ["Validator", "Columns exist, types fit, values are spelled as in the data"],
  ["Compiler", "Quoted identifiers and bound parameters, plus equivalent pandas"],
  ["DuckDB sandbox", "Read-only, no files or network, locked settings, 5 s timeout"],
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

export function CsvArchitecture() {
  return (
    <figure className="rounded-md border border-line bg-surface p-5 text-sm">
      <ol
        className="grid gap-2 md:grid-cols-[repeat(6,minmax(0,1fr))] md:gap-1.5"
        aria-label="Steps"
      >
        {steps.map(([name, note], i) => (
          <li
            key={name}
            className={`rounded-sm px-3 py-2.5 ${i === 2 ? "ring-1 ring-inset ring-link/50" : "bg-surface-2"}`}
          >
            <p className="font-medium text-text">
              <span className="num mr-1.5 text-faint">{i + 1}</span>
              {name}
            </p>
            <p className="mt-1 text-xs text-muted">{note}</p>
          </li>
        ))}
      </ol>

      <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-center">
        <div className="rounded-sm border border-warn/40 px-3 py-2">
          <p className="font-medium text-warn">Language model fallback (optional)</p>
          <p className="text-xs text-muted">
            Only when the rules decline. One tool call fills in the plan; validation errors go back
            to the model for up to 2 retries. Uploads opt in, and send column names only.
          </p>
        </div>
        <Arrow />
        <div className="rounded-sm border border-line-strong px-3 py-2">
          <p className="font-medium text-text">Same plan, same checks</p>
          <p className="text-xs text-muted">
            A model can only produce a plan. It never writes SQL, and its plan goes through the
            validator and compiler exactly like the rules&apos; plan.
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 border-t border-line pt-4 md:grid-cols-3">
        <p className="text-xs text-muted">
          <span className="font-medium text-text">Tables.</span> The retailer&apos;s invoices are
          built into a read-only DuckDB file when the image is built. Uploads become their own
          DuckDB file in memory-backed storage and are deleted after an hour.
        </p>
        <p className="text-xs text-muted">
          <span className="font-medium text-text">Profiling.</span> Every table is profiled before
          the first question: types, gaps, duplicates and values that would run as spreadsheet
          formulas.
        </p>
        <p className="text-xs text-muted">
          <span className="font-medium text-text">Evaluation.</span> Fixed question sets run every 6
          hours against the live table; the latest scores are shown under Results.
        </p>
      </div>
      <figcaption className="sr-only">
        A question goes to the rule-based parser, which produces a query plan. If the rules decline,
        an optional language model may produce a plan instead. Every plan is validated, compiled to
        parameterised SQL and run in a locked-down DuckDB sandbox.
      </figcaption>
    </figure>
  );
}
