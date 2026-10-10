import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink } from "@/components/button-link";
import { JsonLd } from "@/components/json-ld";
import { ProjectSection, ProjectToc } from "@/components/project-page";
import { Pill } from "@/components/status-badge";
import { projects } from "@/content/projects";
import { Analyst } from "@/features/csv/analyst";
import { CsvArchitecture } from "@/features/csv/architecture";
import { serverGet } from "@/lib/api/server";
import type { CsvDataset, CsvEvaluation, CsvEvaluationSet, CsvUsage } from "@/lib/api/types";
import { formatDateTime, formatInt, formatPct } from "@/lib/format";
import { site } from "@/lib/site";

export const revalidate = 60;

const project = projects.find((p) => p.slug === "ai-csv-analyst")!;
const repoTree = `${site.repo}/tree/main/${project.repoPath}`;
const repoFile = (path: string) =>
  `${site.repo}/blob/main/${project.repoPath}/src/reluai_csv/${path}`;

export const metadata: Metadata = {
  title: project.title,
  description:
    "Ask questions of a real 1.07-million-row retail table or your own CSV in plain English. " +
    "A rule-based parser and an optional LLM produce a validated query plan, compiled to " +
    "parameterised SQL and run in a locked-down DuckDB sandbox.",
  alternates: { canonical: `/projects/${project.slug}` },
};

const stack = [
  ["Query engine", "DuckDB 1.5, one read-only database file per table, columnar and in-process"],
  ["Interpretation", "A rule-based parser in plain Python, with an optional function-calling LLM"],
  ["Plans", "Pydantic models with a JSON Schema that doubles as the LLM's tool definition"],
  ["API", "FastAPI, typed responses, RFC 9457 errors, per-visitor quotas, multipart uploads"],
  ["Interface", "Next.js with types generated from the API's OpenAPI document; SVG charts"],
  ["Operations", "Runs in the site's API container; evaluation scheduled on the job queue"],
] as const;

const failures = [
  [
    "The question asks for something the table cannot answer",
    "The rules decline instead of guessing: every word must be understood, so a question about reasons, forecasts or a column that does not exist gets an explanation and suggested questions, not a made-up number.",
  ],
  [
    "A model returns a bad plan",
    "The plan is checked for unknown columns, type mismatches and misspelled values. The problems go back to the model as the tool result, with hints such as the real column names, for up to 2 more attempts. If it still fails, nothing runs and the page says so.",
  ],
  [
    "A model or a question tries to inject SQL",
    "There is no path from text to SQL. A plan names columns, which must exist, and values, which are bound as parameters. Tests send injection strings through the parser, the validator, the compiler and the model fallback.",
  ],
  [
    "SQL reaches the database that should not",
    "The connection is read-only, file and network access are switched off, extensions cannot load and the configuration is locked. Tests run statements such as COPY, ATTACH, INSTALL and read_csv('/etc/passwd') directly against the sandbox and check that each one fails.",
  ],
  [
    "A query is too slow or too big",
    "Every query has a 5-second timeout that interrupts it, a 256 MB memory limit and one thread, and runs one at a time per API process. Results are capped at 100 rows.",
  ],
  [
    "A file is not what it claims",
    "Uploads must be text: Excel, PDF, images, archives and executables are recognised by their first bytes and rejected, as are files with NUL bytes, over 2 MB, over 50,000 rows or over 50 columns. Windows-1252 files are converted to UTF-8.",
  ],
  [
    "The data contains spreadsheet formulas",
    "Profiling flags values that start with =, +, - or @, and the Download CSV button prefixes them so Excel shows them as text instead of running them.",
  ],
  [
    "No model is available",
    "The rules work on their own. Without a model the analyst answers what the rules can read and declines the rest; nothing is paid for and nothing breaks.",
  ],
] as const;

function SetRow({ name, note, s }: { name: string; note: string; s: CsvEvaluationSet }) {
  const answerable = s.questions - s.declined_expected;
  return (
    <tr className="border-b border-line/60 align-top">
      <th scope="row" className="py-2 pr-3 text-left font-normal">
        <span className="font-medium text-text">{name}</span>
        <span className="block max-w-[19rem] text-xs text-faint">{note}</span>
      </th>
      <td className="num py-2 pr-3 text-right">{formatInt(s.questions)}</td>
      <td className="num py-2 pr-3 text-right text-text">
        {formatInt(s.correct)} of {formatInt(answerable)}
      </td>
      <td className={`num py-2 pr-3 text-right ${s.wrong > 0 ? "text-fail" : ""}`}>
        {formatInt(s.wrong)}
      </td>
      <td className="num py-2 pr-3 text-right">{formatInt(s.declined_unexpected)}</td>
      <td className="num py-2 text-right">{formatInt(s.declined_expected)}</td>
    </tr>
  );
}

function ResultsBody({
  evaluation,
  usage,
  dataset,
}: {
  evaluation: CsvEvaluation;
  usage: CsvUsage | null;
  dataset: CsvDataset | null;
}) {
  const misses = evaluation.items.filter(
    (i) => i.set === "held_out" && !["correct", "declined_correctly"].includes(i.outcome),
  );
  const env = evaluation.environment;
  return (
    <>
      <p>
        Two fixed sets of questions run against the live table every 6 hours. A question counts as
        correct when the plan matches the expected plan exactly: same measures, groupings, filters,
        order and limit. The scores below measure the rule-based parser alone.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] text-sm">
          <caption className="sr-only">Evaluation of the rule-based parser</caption>
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th scope="col" className="py-2 pr-3 text-left font-medium">
                Question set
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Questions
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Answered correctly
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Wrong answer
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Declined, should answer
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Declined correctly
              </th>
            </tr>
          </thead>
          <tbody>
            <SetRow
              name="Development"
              note="Written together with the rules, so it shows coverage, not generalisation"
              s={evaluation.development}
            />
            <SetRow
              name="Held out"
              note="Written separately and never used to change the rules"
              s={evaluation.held_out}
            />
          </tbody>
        </table>
      </div>
      <p>
        <strong>The held-out set is the honest number:</strong>{" "}
        {formatPct(evaluation.held_out.accuracy)} of its answerable questions were read correctly.
        Declining is the common failure, which is the safe one: the visitor is told the question was
        not understood and given questions that work. The misses:
      </p>
      <ul className="space-y-2 text-sm">
        {misses.map((m) => (
          <li key={m.question} className="flex flex-wrap gap-x-3">
            <span className="text-text">“{m.question}”</span>
            <span className={m.outcome === "wrong" ? "text-fail" : "text-muted"}>
              {m.outcome === "wrong"
                ? `answered wrongly: ${m.summary ?? ""}`
                : m.outcome === "declined"
                  ? "declined"
                  : "answered although it should have declined"}
            </span>
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 py-2 sm:grid-cols-4">
        {(
          [
            ["Median query time", `${evaluation.query_p50_ms} ms`],
            ["95th percentile query time", `${evaluation.query_p95_ms} ms`],
            ["Rows in the table", formatInt(Number(env.rows ?? dataset?.rows ?? 0))],
            ["Questions from visitors, 30 days", usage ? formatInt(usage.questions) : "–"],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="flex flex-col-reverse border-t border-line pt-3">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className="num text-lg font-semibold text-text">{value}</dd>
          </div>
        ))}
      </dl>
      {usage && usage.questions > 0 && (
        <p>
          Of the visitors&apos; questions in the last 30 days, {formatInt(usage.answered_by_rules)}{" "}
          were answered by the rules, {formatInt(usage.answered_by_llm)} by a language model, and{" "}
          {formatInt(usage.not_understood)} were not understood. Only these outcomes are recorded,
          never the question text.
        </p>
      )}
      <p className="text-sm text-faint">
        Last evaluated {formatDateTime(evaluation.ran_at)} on {String(env.cpu)} with{" "}
        {String(env.cpus)} vCPU, DuckDB {String(env.duckdb)}, {String(env.query_threads)} query
        thread and a {String(env.memory_limit)} memory limit. Query time covers executing the
        compiled SQL and fetching the rows.
      </p>
    </>
  );
}

export default async function CsvAnalystPage() {
  const [dataset, evaluation, usage] = await Promise.all([
    serverGet<CsvDataset>("/api/csv/datasets/retail", revalidate),
    serverGet<CsvEvaluation>("/api/csv/evaluation", revalidate),
    serverGet<CsvUsage>("/api/csv/usage", revalidate),
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
          Ask a table a question in plain English and see exactly what was run. It reads a real
          retailer&apos;s 1.07 million invoice lines or a CSV you upload, reports data-quality
          problems first, and answers with a chart, the SQL and the same query in pandas.
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Pill tone="pass">Live</Pill>
          <Pill>AI and LLM apps</Pill>
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
              A manager has a spreadsheet export and a simple question: which countries grew last
              year, how many customers ordered in March. Getting the answer means waiting for an
              analyst, or writing formulas over data they have not checked.
            </p>
            <p>
              Chat assistants that &ldquo;talk to your data&rdquo; make the first part easy and the
              second part worse. They write SQL or code nobody reads, answer confidently when the
              question does not match the data, and say nothing about duplicates, gaps or numbers
              stored as text that make the total wrong.
            </p>
          </ProjectSection>

          <ProjectSection id="why">
            <p>
              A wrong number that looks right is worse than no number. For a tool like this to be
              trusted in a business, the reader has to be able to see what was computed, the system
              has to say when it does not understand, and it must be impossible for a question, or a
              model, to change or leak data.
            </p>
            <p>
              Those are the properties this project is built around, and the ones its tests check.
            </p>
          </ProjectSection>

          <ProjectSection id="solution">
            <p>
              Before any question, the table is profiled: column types, missing values, duplicate
              rows, negative amounts, numbers stored as text and values that would run as
              spreadsheet formulas.
            </p>
            <p>
              A question is turned into a query plan: which measures, grouped by what, filtered how,
              sorted and limited. A rule-based parser does this first, without any model. It knows
              the table&apos;s columns, their synonyms and their values, and it declines any
              question containing a word it does not understand. Only if the rules decline can a
              language model fill in the same plan through one function call.
            </p>
            <p>
              Every plan, from either source, is validated against the table and compiled to
              parameterised SQL. The answer shows the plan as a sentence, the result as a chart and
              table, the SQL that ran, and the same query in pandas.
            </p>
          </ProjectSection>

          <ProjectSection id="architecture">
            <CsvArchitecture />
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
              <strong>The plan.</strong> Up to 3 measures (count, distinct count, sum, average,
              minimum, maximum), up to 2 groupings including a time bucket (day to year), up to 6
              filters, a sort and a limit of at most 100 rows. The same Pydantic model validates the
              rules&apos; output and the model&apos;s tool call, and its JSON Schema is the tool
              definition.
            </p>
            <p>
              <strong>The parser.</strong> Questions are split into the longest phrases it knows:
              column names and synonyms (&ldquo;spent&rdquo; means revenue, &ldquo;orders&rdquo;
              means invoices), values with their aliases (&ldquo;UK&rdquo;, &ldquo;Ireland&rdquo; as
              EIRE), dates and periods, numbers with currency signs and separators, and about 120
              keyword phrases. Passes for filters, groupings and measures then build the plan. If
              any word is left over, it declines.
            </p>
            <p>
              <strong>Dates.</strong> &ldquo;In 2011&rdquo; is the whole year, &ldquo;before March
              2011&rdquo; means before 1 March, &ldquo;after 2010&rdquo; starts on 1 January 2011.
              Ranges are compiled as half-open intervals on whole days, so timestamps at 23:59 are
              never lost.
            </p>
            <p>
              <strong>Checked equivalence.</strong> Tests run 24 plans through the SQL and through
              the displayed pandas code on the same data and require identical rows, including how
              missing values are treated.
            </p>
          </ProjectSection>

          <ProjectSection id="demo">
            <p>
              Ask about the retailer&apos;s invoices, or upload a CSV of your own. Questions about
              totals, counts, averages, rankings and trends work best. Every answer shows how the
              question was read, so you can tell when it was read wrongly.
            </p>
            <div className="pt-2 text-base">
              <Analyst initialDataset={dataset.ok ? dataset.data : undefined} />
            </div>
            <p className="text-sm text-faint">
              Portfolio demonstration. Each visitor can ask 60 questions and upload 10 files per
              hour.
            </p>
          </ProjectSection>

          <ProjectSection id="results">
            {evaluation.ok ? (
              <ResultsBody
                evaluation={evaluation.data}
                usage={usage.ok ? usage.data : null}
                dataset={dataset.ok ? dataset.data : null}
              />
            ) : (
              <p>
                Results are read from the running system and are not available right now. They
                return when the analyst service is reachable and has run its first evaluation.
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
              The analyst runs inside the site&apos;s API container on the same 2 vCPU, 8 GB server
              as the other projects. The retailer table is built into the image from the verified
              dataset download, so it is identical on every deploy. Uploads live in a memory-backed
              temporary folder inside the container and disappear on restart if not before.
            </p>
            <p>
              The evaluation runs on the job queue every 6 hours and stores its scores, which the
              Results section reads. Releases go through the same pipeline as the rest of the site:
              tests, image build and scan, deployment with a health check and automatic rollback.
            </p>
          </ProjectSection>

          <ProjectSection id="cost">
            <p>
              <strong>$0 in API spend.</strong> The rules answer without any model. The optional
              fallback uses free-tier providers only (Groq, then Cerebras) through a token ledger
              that stops at a daily budget below the free limit and reserves a share for
              demonstrations. When neither is configured or both are exhausted, the analyst keeps
              working with the rules alone.
            </p>
            <p>
              DuckDB answers most questions on the 1.07-million-row table in tens of milliseconds on
              one thread, so the analyst adds no noticeable load to the shared server.
            </p>
          </ProjectSection>

          <ProjectSection id="limitations">
            <ul className="list-disc space-y-1.5 pl-5">
              <li>
                Answers are aggregates. It does not list individual rows, join tables, compute
                shares or ratios (&ldquo;what share of revenue comes from the UK?&rdquo;), or filter
                on an aggregate (&ldquo;countries with fewer than 100 customers&rdquo;); it declines
                those.
              </li>
              <li>
                The rules know a fixed vocabulary. Phrasings outside it are declined unless a model
                is available, and the held-out score above shows how often that happens.
              </li>
              <li>
                It can still misread. On the held-out set, &ldquo;Revenue from customers in EIRE per
                year&rdquo; also counted the customers, because &ldquo;customers&rdquo; was read as
                a measure. The interpretation is always shown so such misreadings are visible.
              </li>
              <li>
                Uploaded columns are typed by DuckDB&apos;s CSV reader. Numbers written with
                thousands separators are read as text (the profile says so) and cannot be summed.
              </li>
              <li>
                The model fallback has not been scored, because this server runs without a model by
                default. When one is configured, its answers are labelled with the provider and
                model.
              </li>
            </ul>
          </ProjectSection>

          <ProjectSection id="source">
            <p>
              The full source is on GitHub under the MIT licence, with the tests and the evaluation
              sets.
            </p>
            <ul className="space-y-2">
              {(
                [
                  ["parser.py", "Rule-based question parser"],
                  ["plan.py", "The query plan and its JSON Schema"],
                  ["validate.py", "Checks a plan against the table and normalises it"],
                  ["compile.py", "Plan to parameterised SQL, pandas and a plain-English summary"],
                  ["sandbox.py", "Locked-down DuckDB execution with timeouts"],
                  ["llm.py", "Function-calling fallback with validation retries"],
                  ["profile.py", "Profiling and data-quality findings"],
                  ["evaluation.py", "Development and held-out question sets"],
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
