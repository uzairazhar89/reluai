import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink } from "@/components/button-link";
import { JsonLd } from "@/components/json-ld";
import { ProjectSection, ProjectToc } from "@/components/project-page";
import { Pill } from "@/components/status-badge";
import { projects } from "@/content/projects";
import { PipelineArchitecture } from "@/features/pipeline/architecture";
import { PipelineDashboard } from "@/features/pipeline/dashboard";
import { serverGet } from "@/lib/api/server";
import type { Results, Run, Summary } from "@/lib/api/types";
import { formatDropKey, formatDuration, formatInt, formatPct, formatScore } from "@/lib/format";
import { site } from "@/lib/site";

export const revalidate = 60;

const project = projects.find((p) => p.slug === "data-pipeline-observatory")!;
const repoTree = `${site.repo}/tree/main/${project.repoPath}`;
const repoFile = (path: string) =>
  `${site.repo}/blob/main/${project.repoPath}/src/reluai_pipeline/${path}`;

export const metadata: Metadata = {
  title: project.title,
  description:
    "A Python ETL pipeline on 1.07 million real retail invoice lines: data contract, quarantine " +
    "with reason codes, idempotent PostgreSQL loads, quality gates and a live run dashboard.",
  alternates: { canonical: `/projects/${project.slug}` },
};

const stack = [
  [
    "Pipeline",
    "Python 3.13, pandas, tenacity, a data contract and reason-code registry in plain Python",
  ],
  ["Storage", "PostgreSQL 16: warehouse schema, quarantine, run metadata and the job queue"],
  [
    "Jobs",
    "Procrastinate (PostgreSQL-backed queue) with a periodic schedule and a global CPU lease",
  ],
  ["API", "FastAPI and Pydantic, typed responses, RFC 9457 error bodies, per-visitor quotas"],
  ["Interface", "Next.js with types generated from the API's OpenAPI document"],
  [
    "Operations",
    "Docker images built and scanned in CI, nginx, structured JSON logs, Prometheus metrics",
  ],
] as const;

const failures = [
  [
    "The CRM API is slow or returns errors",
    "Each page request is tried up to 4 times, with exponential backoff and jitter between attempts. Every retry is logged and counted on the run. Try the Flaky CRM API scenario.",
  ],
  [
    "The CRM is down for the whole run",
    "Retries are exhausted, the run fails at the extract step and nothing is written. The warehouse keeps the last good state. Try the CRM outage scenario.",
  ],
  [
    "A file arrives damaged",
    "Damaged lines are caught one at a time (wrong field count, invalid bytes, wrong date format, text in a number column) and quarantined with their line number. If the quarantined share passes 5%, the quality gate stops the run before any write. Try the Corrupted file drop scenario.",
  ],
  [
    "The same file is processed twice",
    "Every line has a stable key derived from its content, and loads insert only keys that are not already present. Replaying a drop writes 0 new rows, and the run says so.",
  ],
  [
    "A load is interrupted or incomplete",
    "Each drop loads in one transaction. After the load, a reconciliation check counts the drop's lines in the warehouse and fails the run if any are missing, rolling the transaction back.",
  ],
  [
    "A worker dies mid-run",
    "A housekeeping job marks runs stuck in the running state for too long as failed, so the dashboard never shows a run that will not finish.",
  ],
  [
    "Too many visitors start runs",
    "Each visitor can start 3 runs per hour, at most 4 runs can wait in the queue, and nginx limits request rates. Runs execute one at a time under a CPU lease so the rest of the site stays responsive.",
  ],
] as const;

function ResultsBody({ results }: { results: Results }) {
  const t = results.totals;
  const dec2010 = results.drops.find((d) => d.drop_key === "2010-12");
  return (
    <>
      <p>
        Measured on the running system, using the most recent successful run of each monthly drop.
        These figures update as scheduled runs load more months.
      </p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 py-2 sm:grid-cols-4">
        {(
          [
            ["Monthly drops loaded", formatInt(t.drops)],
            ["Rows read", formatInt(t.rows_read)],
            [
              "Rows quarantined",
              `${formatInt(t.rows_rejected)} (${formatPct(t.rows_read ? t.rows_rejected / t.rows_read : null, 2)})`,
            ],
            ["Duplicate lines removed", formatInt(t.rows_deduplicated)],
            ["Lines published", formatInt(t.rows_published)],
            ["Median run time", formatDuration(results.duration.median_ms)],
            ["95th percentile run time", formatDuration(results.duration.p95_ms)],
            [
              "Runs succeeded / failed",
              `${formatInt(results.runs_succeeded)} / ${formatInt(results.runs_failed)}`,
            ],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="flex flex-col-reverse border-t border-line pt-3">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className="num text-lg font-semibold text-text">{value}</dd>
          </div>
        ))}
      </dl>
      {dec2010 && (
        <p>
          <strong>A real issue the checks caught.</strong> The December 2010 drop contains{" "}
          {formatInt(dec2010.rows_deduplicated)} exact duplicate lines, almost all dated 1 to 9
          December: the period where the source workbook&apos;s two yearly sheets overlap. The
          pipeline removed them, and the duplicate-ratio check failed as a warning, which is why
          that month scores {formatScore(dec2010.dq_score)} rather than 100.
        </p>
      )}
      <p>
        Failed runs in the count above include the simulated fault scenarios, which are meant to
        fail.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm sm:min-w-[640px]">
          <caption className="sr-only">Latest successful result for each monthly drop</caption>
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th className="py-2 pr-3 font-medium">Drop</th>
              <th className="py-2 pr-3 text-right font-medium">Read</th>
              <th className="py-2 pr-3 text-right font-medium">Quarantined</th>
              <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Duplicates</th>
              <th className="py-2 pr-3 text-right font-medium">Published</th>
              <th className="py-2 pr-3 text-right font-medium">Quality</th>
              <th className="hidden py-2 text-right font-medium sm:table-cell">Run time</th>
            </tr>
          </thead>
          <tbody className="text-text">
            {results.drops.map((d) => (
              <tr key={d.drop_key} className="border-b border-line/60">
                <td className="py-1.5 pr-3">{formatDropKey(d.drop_key)}</td>
                <td className="num py-1.5 pr-3 text-right">{formatInt(d.rows_read)}</td>
                <td className="num py-1.5 pr-3 text-right text-muted">
                  {formatInt(d.rows_rejected)}
                </td>
                <td className="num hidden py-1.5 pr-3 text-right text-muted sm:table-cell">
                  {formatInt(d.rows_deduplicated)}
                </td>
                <td className="num py-1.5 pr-3 text-right">{formatInt(d.rows_published)}</td>
                <td
                  className={`num py-1.5 pr-3 text-right ${d.dq_score !== null && d.dq_score !== undefined && d.dq_score < 100 ? "text-warn" : ""}`}
                >
                  {formatScore(d.dq_score)}
                </td>
                <td className="num hidden py-1.5 text-right text-muted sm:table-cell">
                  {formatDuration(d.duration_ms)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {results.environment && (
        <p className="text-sm text-faint">
          Measured on {String(results.environment.cpu)} with {String(results.environment.cpu_count)}{" "}
          vCPU ({String(results.environment.environment)} environment), Python{" "}
          {String(results.environment.python)}, pandas {String(results.environment.pandas)}. Run
          time covers all steps from resolving the drop to the committed load.
        </p>
      )}
    </>
  );
}

export default async function PipelineProjectPage() {
  const renderedAt = new Date().toISOString();
  const [summary, runs, results] = await Promise.all([
    serverGet<Summary>("/api/pipeline/summary", revalidate),
    serverGet<Run[]>("/api/pipeline/runs?limit=25", revalidate),
    serverGet<Results>("/api/pipeline/results", revalidate),
  ]);

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "SoftwareSourceCode",
          name: project.title,
          description: metadata.description,
          codeRepository: repoTree,
          programmingLanguage: ["Python", "SQL", "TypeScript"],
          author: { "@type": "Person", name: site.name, url: site.url },
          license: "https://opensource.org/licenses/MIT",
        }}
      />

      <header className="mx-auto max-w-6xl px-5 pb-12 pt-12 sm:px-8 md:pt-16">
        <nav aria-label="Breadcrumb" className="text-sm text-muted">
          <Link href="/projects" className="hover:text-text">
            Projects
          </Link>
          <span aria-hidden className="mx-2 text-faint">
            /
          </span>
          <span aria-current="page">{project.title}</span>
        </nav>
        <h1 className="display mt-5 max-w-[22ch] text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">
          {project.title}
        </h1>
        <p className="mt-5 max-w-[62ch] text-lg text-muted">
          A production-style ETL pipeline on 1.07 million real invoice lines from a UK online gift
          retailer. It validates every row, quarantines what it cannot trust with a reason, loads
          PostgreSQL without duplicates and refuses to publish a batch that fails its quality gate.
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Pill tone="pass">Live</Pill>
          <Pill>Data engineering</Pill>
          <Pill>{project.dataNote ?? "Real data"}</Pill>
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <ButtonLink href="#demo">Try the live demo</ButtonLink>
          <ButtonLink href={repoTree} variant="secondary" external>
            Source code
          </ButtonLink>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-12 px-5 pb-24 sm:px-8 lg:grid-cols-[12rem_minmax(0,1fr)]">
        <ProjectToc />
        <div className="min-w-0 space-y-14">
          <ProjectSection id="problem">
            <p>
              Most companies run reports on data that arrives from several systems that do not
              agree. Here, a retailer has three: a monthly invoice export, a product catalogue and a
              CRM with its customer register. The export is real, and so are its problems:
            </p>
            <ul className="list-disc space-y-1.5 pl-5">
              <li>Cancellations recorded as separate invoices with negative quantities.</li>
              <li>Exact duplicate lines, including thousands from overlapping export periods.</li>
              <li>
                Stock write-offs (damaged, missing, re-labelled) recorded as zero-price lines with
                no customer.
              </li>
              <li>
                Bad-debt adjustments, test records, postage and manual lines mixed in with product
                sales.
              </li>
              <li>
                More than a fifth of lines with no customer ID, and stock codes in inconsistent
                case.
              </li>
            </ul>
            <p>
              Summed naively, this data overstates sales, double-counts customers and misattributes
              revenue. Nobody notices until a number in a board pack is wrong.
            </p>
          </ProjectSection>

          <ProjectSection id="why">
            <p>
              Analysts typically spend more time cleaning and reconciling data than analysing it,
              and the cleaning is usually manual, undocumented and repeated every month. When it
              happens in a spreadsheet, nobody can say which rows were removed or why.
            </p>
            <p>
              A pipeline that applies the same written rules every time, keeps every rejected row
              with its reason, and stops rather than publishing bad data turns that monthly chore
              into something auditable. It is also the foundation the later projects on this site
              build on: the CSV analyst, the document assistant and the support agent all read this
              warehouse.
            </p>
          </ProjectSection>

          <ProjectSection id="solution">
            <p>
              Each month&apos;s file goes through five steps. Rows are checked against a data
              contract and a set of business rules; every rule has a reason code and a plain
              explanation. Failing rows go to quarantine with their original content and line
              number. Rows that are real but imperfect (a guest sale with no customer ID) are
              published with a warning instead of being thrown away.
            </p>
            <p>
              Before anything is written, batch-level checks score the drop. A failed gate check
              stops the run. Passing drops are loaded in one transaction, reconciled against the
              warehouse, and recorded with their steps, log lines and check results so any past run
              can be inspected.
            </p>
          </ProjectSection>

          <ProjectSection id="architecture">
            <PipelineArchitecture />
            <p>
              The product catalogue and CRM register are derived from the same public dataset but
              served as separate sources, a JSON file and a paginated REST API, so the pipeline
              faces the integration problems of a real setup: joins across systems, pagination and
              an upstream service that can fail.
            </p>
          </ProjectSection>

          <ProjectSection id="implementation">
            <dl className="divide-y divide-line/60">
              {stack.map(([term, desc]) => (
                <div key={term} className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr] sm:gap-6">
                  <dt className="font-medium text-text">{term}</dt>
                  <dd>{desc}</dd>
                </div>
              ))}
            </dl>
            <p>
              <strong>Data contract.</strong> The header must match an 8-column contract exactly.
              Lines are parsed one at a time, so a single truncated line or invalid byte sequence
              becomes one quarantined row rather than a failed file.
            </p>
            <p>
              <strong>Rules with reason codes.</strong> 18 rejection rules and 5 warning rules, each
              with a code, a severity and an explanation shown in the dashboard. Rules are evaluated
              in a fixed order, so every quarantined row has exactly one primary reason.
            </p>
            <p>
              <strong>Idempotent loads.</strong> Each line&apos;s key is a SHA-256 hash of its
              normalised content. Rows are bulk-copied into temporary tables and inserted with{" "}
              <code className="font-mono text-sm text-text">ON CONFLICT DO NOTHING</code>, so
              reprocessing never creates duplicates.
            </p>
            <p>
              <strong>Quality score.</strong> 9 checks across validity, uniqueness, completeness,
              timeliness, integrity and accuracy. Score = 100 × Σ(weight × passed) / Σ(weight), with
              weights of 3 for gate checks, 2 for warnings and 1 for information. The formula is
              shown under every run.
            </p>
          </ProjectSection>

          <ProjectSection id="demo">
            <p>
              Start a run and watch it move through the steps. The standard scenario loads the next
              month of real invoices; the simulated scenarios inject failures so you can see how
              each one is handled. Select any run to see its checks, quarantined rows and log.
            </p>
            <div className="pt-2 text-base">
              <PipelineDashboard
                renderedAt={renderedAt}
                initialSummary={summary.ok ? summary.data : undefined}
                initialRuns={runs.ok ? runs.data : undefined}
              />
            </div>
          </ProjectSection>

          <ProjectSection id="results">
            {results.ok && results.data.drops.length > 0 ? (
              <ResultsBody results={results.data} />
            ) : (
              <p>
                Results are read from the running system and are not available right now. They
                return when the pipeline service is reachable again.
              </p>
            )}
          </ProjectSection>

          <ProjectSection id="failure-handling">
            <dl className="divide-y divide-line/60">
              {failures.map(([term, desc]) => (
                <div key={term} className="py-3.5">
                  <dt className="font-medium text-text">{term}</dt>
                  <dd className="mt-1">{desc}</dd>
                </div>
              ))}
            </dl>
          </ProjectSection>

          <ProjectSection id="deployment">
            <p>
              The pipeline runs as a worker container next to the API, the website, nginx and
              PostgreSQL on a single 2 vCPU, 8 GB virtual server. Every push runs linting, type
              checks and tests, including database tests against a real PostgreSQL. Release images
              are built once, scanned for vulnerabilities and published with a software bill of
              materials.
            </p>
            <p>
              Deployment pulls the tagged images, applies database migrations, restarts the services
              and checks health through nginx. If the health check fails, the previous version is
              restored automatically. A scheduled run every 6 hours keeps the dashboard current, and
              the database is backed up every night.
            </p>
          </ProjectSection>

          <ProjectSection id="cost">
            <p>
              <strong>$0 in API spend.</strong> The pipeline uses no paid services or AI models. It
              shares the site&apos;s existing server; the worker container is limited to 1 CPU and
              1.5 GB of memory, and a month of invoices (30,000 to 80,000 lines) typically processes
              in a few seconds.
            </p>
            <p>
              For a real deployment the same design runs on any machine with Docker and PostgreSQL.
              The main cost driver would be data volume: loads use PostgreSQL&apos;s bulk COPY, so
              they scale with disk throughput rather than per-row round trips.
            </p>
          </ProjectSection>

          <ProjectSection id="limitations">
            <ul className="list-disc space-y-1.5 pl-5">
              <li>
                The data is historical (December 2009 to December 2011) and is shown with its real
                dates. It is not shifted to look recent.
              </li>
              <li>
                The catalogue and CRM are derived from the invoice data, so they cannot disagree
                with it in all the ways real systems do. The fault scenarios cover the important
                failure modes, and are clearly labelled as simulated.
              </li>
              <li>
                pandas holds one monthly file in memory. That is appropriate at this volume; much
                larger drops would call for chunked reads or a columnar engine such as DuckDB or
                Polars.
              </li>
              <li>
                Runs execute one at a time by design, to protect a small shared server. A busy
                production system would use dedicated workers.
              </li>
            </ul>
          </ProjectSection>

          <ProjectSection id="source">
            <p>
              The full source is on GitHub under the MIT licence, together with the tests and the
              infrastructure that deploys it.
            </p>
            <ul className="space-y-2">
              {(
                [
                  ["contract.py", "Data contract and line-by-line parsing"],
                  ["rules.py", "Reason-code registry and rule order"],
                  ["validate.py", "Business, period and referential rules, de-duplication"],
                  ["load.py", "Bulk copy, upserts and reconciliation"],
                  ["quality.py", "Data-quality checks and score"],
                  ["runner.py", "Run orchestration and step recording"],
                ] as const
              ).map(([file, what]) => (
                <li key={file} className="flex flex-wrap gap-x-3">
                  <a href={repoFile(file)} className="prose-link font-mono text-sm">
                    {file}
                  </a>
                  <span>{what}</span>
                </li>
              ))}
            </ul>
            <p>
              Tests cover the contract, each rule, idempotent replays, every fault scenario, and a
              regression test that runs the real December 2010 drop and checks its exact counts.
            </p>
            <div className="pt-2">
              <ButtonLink href={repoTree} variant="secondary" external>
                View on GitHub
              </ButtonLink>
            </div>
            <p className="text-sm text-faint">
              Data: Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository, CC
              BY 4.0. Details on the{" "}
              <Link href="/data" className="prose-link">
                data page
              </Link>
              .
            </p>
          </ProjectSection>
        </div>
      </div>
    </>
  );
}
