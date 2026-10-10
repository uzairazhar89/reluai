import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink } from "@/components/button-link";
import { JsonLd } from "@/components/json-ld";
import { ProjectSection, ProjectToc } from "@/components/project-page";
import { Pill } from "@/components/status-badge";
import { projects } from "@/content/projects";
import { AgentDemo } from "@/features/support/agent-demo";
import { SupportArchitecture } from "@/features/support/architecture";
import { serverGet } from "@/lib/api/server";
import type { SupportCatalogue, SupportEvaluationRun } from "@/lib/api/types";
import { formatDateTime, formatInt } from "@/lib/format";
import { site } from "@/lib/site";

export const revalidate = 60;

const project = projects.find((p) => p.slug === "support-agent")!;
const repoTree = `${site.repo}/tree/main/${project.repoPath}`;
const repoFile = (path: string) =>
  `${site.repo}/blob/main/${project.repoPath}/src/reluai_support/${path}`;

export const metadata: Metadata = {
  title: project.title,
  description:
    "A tool-calling support agent that resolves order questions about real invoices: " +
    "validated tools, refund rules in code, policy citations, supervisor approval for large " +
    "refunds and a full trace of every step.",
  alternates: { canonical: `/projects/${project.slug}` },
};

const stack = [
  ["Agent loop", "Written by hand against the OpenAI-compatible chat API; no agent framework"],
  ["Models", "Groq and Cerebras free tiers when configured, a scripted agent as the last step"],
  ["Tools", "Eight Python functions with Pydantic argument models, scoped to one customer"],
  ["Data", "Real invoices in a read-only DuckDB snapshot; policy search in PostgreSQL"],
  ["API", "FastAPI with per-visitor quotas; conversations kept for 24 hours"],
  ["Interface", "Next.js: chat, supervisor approval and a step-by-step trace"],
] as const;

const failures = [
  [
    "The model proposes invalid arguments or an unknown tool",
    "Arguments are validated before anything runs. The error goes back to the model as the tool result, so it can correct itself on the next step.",
  ],
  [
    "The model, or the customer, tries to raise a refund",
    "Refund amounts come only from calculate_refund. request_approval refuses any amount that differs from the rules' result by more than a penny, and refuses to run before a calculation.",
  ],
  [
    "A customer asks about someone else's order",
    "Every tool is scoped to the conversation's customer. Another customer's invoice gets the same answer as an invoice that does not exist, so nothing leaks.",
  ],
  [
    "The agent loops or stalls",
    "A turn stops after 8 steps or 25 seconds. The conversation is then handed to a person with a ticket, and the customer is told so.",
  ],
  [
    "No model is available, or the free tier is used up",
    "The provider chain falls through to the scripted agent, which uses the same tools and rules. The trace says which provider answered each step and why earlier ones were skipped.",
  ],
  [
    "A large refund needs a decision",
    "Above £50 the agent can only request approval. The conversation pauses, the visitor decides as supervisor, and the agent drafts the follow-up from the decision.",
  ],
  [
    "Anything would reach a real person or account",
    "Nothing can: refunds, tickets and replies are records in this demo's database, deleted after a day.",
  ],
] as const;

function RunTable({ runs }: { runs: SupportEvaluationRun[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <caption className="sr-only">Scenario results per provider</caption>
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th scope="col" className="py-2 pr-3 text-left font-medium">
              Agent
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Scenarios passed
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Model tokens
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Median time
            </th>
            <th scope="col" className="py-2 text-left font-medium">
              Run
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.label} className="border-b border-line/60">
              <th scope="row" className="py-2 pr-3 text-left font-medium text-text">
                {r.label === "scripted" ? "Scripted agent (no model)" : r.label}
              </th>
              <td className="num py-2 pr-3 text-right text-text">
                {r.passed} of {r.scenarios}
              </td>
              <td className="num py-2 pr-3 text-right">{formatInt(r.tokens)}</td>
              <td className="num py-2 pr-3 text-right">{r.median_latency_ms} ms</td>
              <td className="py-2 text-muted">{formatDateTime(r.ran_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultsBody({ runs, order }: { runs: SupportEvaluationRun[]; order: string[] }) {
  const scripted = runs.find((r) => r.label === "scripted");
  const rank = (c: string) => (order.includes(c) ? order.indexOf(c) : order.length);
  const models = runs.filter((r) => r.label !== "scripted");
  return (
    <>
      <p>
        A fixed suite of customer scenarios on real invoices: damaged and missing items inside and
        outside the reporting window, late and lost parcels, returns, credit notes, invoice
        questions, messages without an invoice number, another customer&apos;s invoice and two
        prompt-injection attempts. A scenario passes only if the refunds recorded (amount from the
        rules for the expected items), approvals, tickets and reply are all right.
      </p>
      <RunTable runs={runs} />
      {scripted && (
        <p>
          <strong>Read the scripted result as a check, not a score.</strong> The scripted agent was
          written alongside the scenarios, so {scripted.passed} of {scripted.scenarios} shows that
          the tools, rules, approvals and trace work end to end without any model. It says nothing
          about understanding language: it reads keywords and product names.
        </p>
      )}
      {models.length === 0 ? (
        <p>
          <strong>No model has been scored yet.</strong> This server runs without a model by default
          ($0 budget). When a free-tier key is configured, the same suite is run against the model
          with{" "}
          <code className="font-mono text-sm text-text">
            reluai-support evaluate --provider groq
          </code>{" "}
          and its result appears in this table. A run that hits a provider outage or a free-tier
          limit is not recorded, because it would measure capacity rather than the agent.
        </p>
      ) : (
        <p>
          Model runs use the same scenarios and checks, with no scripted fallback, so a model
          failure counts as a failure.
        </p>
      )}
      {scripted && (
        <div className="max-w-md">
          <table className="w-full text-sm">
            <caption className="sr-only">Scripted agent by scenario category</caption>
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th scope="col" className="py-2 pr-3 text-left font-medium">
                  Category
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  Passed
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(scripted.by_category)
                .sort(([a], [b]) => rank(a) - rank(b))
                .map(([category, [passed, total]]) => (
                  <tr key={category} className="border-b border-line/60">
                    <td className="py-1.5 pr-3 text-text">{category}</td>
                    <td className="num py-1.5 text-right">
                      {passed} of {total}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default async function SupportAgentPage() {
  const [catalogue, evaluation] = await Promise.all([
    serverGet<SupportCatalogue>("/api/support/catalogue", revalidate),
    serverGet<SupportEvaluationRun[]>("/api/support/evaluation", revalidate),
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
          programmingLanguage: ["Python", "TypeScript"],
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
          A tool-calling agent that answers order questions from the retailer&apos;s real customers
          about their real invoices. It looks things up, applies the refund policy in code, cites
          the policy, and stops for a person before any refund over £50. Every step is shown.
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Pill tone="pass">Live</Pill>
          <Pill>AI and LLM apps</Pill>
          <Pill>Real invoices</Pill>
          <Pill tone="warn">Simulated: shipments, policy, messages</Pill>
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
              Most customer messages to an online shop are about one order: something arrived
              broken, something is missing, a parcel is late. Answering them means opening the
              invoice, checking tracking, reading the policy and working out what is owed. It is
              repetitive, and mistakes cost money in both directions.
            </p>
            <p>
              Chatbots that answer from a prompt alone make it worse: they promise refunds the
              policy does not allow, invent order details, and can be talked into things.
            </p>
          </ProjectSection>

          <ProjectSection id="why">
            <p>
              An agent is only useful in operations if it is safe to let it act. That means its
              facts come from systems, its amounts from rules, its actions are limited and
              reviewable, and a person decides anything significant. Those are the properties this
              project demonstrates, with a trace that lets anyone check what happened.
            </p>
          </ProjectSection>

          <ProjectSection id="solution">
            <p>
              The agent works through tools. It reads the invoice and the tracking, searches the
              policy, and asks the refund rules what is due. It can record a refund only for the
              exact amount the rules returned: up to £50 it does so itself; above that, it asks for
              approval and the conversation waits for the supervisor. It opens tickets for work a
              person must do and drafts a reply that cites the policy. Nothing is sent and no money
              moves.
            </p>
            <p>
              A free-tier model drives the loop when one is configured. Without one, a scripted
              agent takes the same steps with the same tools, so the demo always works and the
              difference between the two can be measured.
            </p>
          </ProjectSection>

          <ProjectSection id="architecture">
            <SupportArchitecture />
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
              <strong>The loop.</strong> Each step sends the conversation and the tool definitions
              to the provider chain. All tool calls in a response run as a batch (looking up the
              invoice and its tracking happens in one step), each result is returned to the model,
              and the loop ends when the agent drafts a reply or a refund needs approval. A
              supervisor&apos;s decision is added to the conversation and the loop resumes.
            </p>
            <p>
              <strong>Refund rules.</strong> Damaged or missing items within 14 days of delivery,
              late deliveries (more than 3 days after the estimate: the shipping charge, or 5% of
              the goods up to £10), lost parcels (10 days past the estimate) and returns within 30
              days (refunded on receipt). Credit notes are never refunded again.
            </p>
            <p>
              <strong>Real and simulated data.</strong> Invoices come from 797,885 real invoice
              lines of customers with an ID, after removing the source export&apos;s duplicate
              lines. Shipments are simulated from each invoice&apos;s number and date, so the same
              invoice always has the same tracking; carrier services have generic names. The desk
              works as of 10 December 2011, the day after the data ends.
            </p>
            <p>
              <strong>Policy search.</strong> The policy is split into passages by section and
              searched with PostgreSQL full-text search through the shared retrieval package;
              passages are numbered so replies can cite them, and a reply cannot cite a passage the
              agent did not retrieve.
            </p>
          </ProjectSection>

          <ProjectSection id="demo">
            <p>
              Pick a scenario, or write your own message as one of the customers. The left side
              shows the conversation; the right side shows every step the agent took. When a refund
              needs approval, you decide.
            </p>
            <div className="pt-2 text-base">
              <AgentDemo initialCatalogue={catalogue.ok ? catalogue.data : undefined} />
            </div>
            <p className="text-sm text-faint">
              Portfolio demonstration. Customers and invoices are real (anonymised by the source);
              shipments, the policy, tickets and messages are simulated. Each visitor can start 20
              conversations an hour.
            </p>
          </ProjectSection>

          <ProjectSection id="results">
            {evaluation.ok && evaluation.data.length > 0 ? (
              <ResultsBody
                runs={evaluation.data}
                order={[
                  ...new Set((catalogue.ok ? catalogue.data.scenarios : []).map((s) => s.category)),
                ]}
              />
            ) : (
              <p>
                Results are read from the running system and are not available right now. They
                appear after the first scheduled run of the scenario suite.
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
              The agent runs in the site&apos;s API container. The order snapshot is built into the
              image from the verified dataset download; the policy is indexed into PostgreSQL the
              first time it is searched. Conversations are stored for 24 hours and removed by a
              daily job, which also re-runs the scripted baseline.
            </p>
            <p>
              nginx gives the agent&apos;s routes a longer read timeout (a turn with a model can
              take several seconds) and a stricter request rate than the rest of the API.
            </p>
          </ProjectSection>

          <ProjectSection id="cost">
            <p>
              <strong>$0 in API spend.</strong> Only free tiers are ever used, through a token
              ledger with daily limits per provider and per visitor. When the limits are reached the
              chain falls through to the scripted agent, which costs nothing.
            </p>
            <p>
              Every model step resends the instructions and the eight tool definitions, about 5,600
              characters (roughly 1,400 tokens by the ledger&apos;s estimate of four characters per
              token), plus the conversation and tool results so far. The trace shows the measured
              tokens of each step when a model answers.
            </p>
          </ProjectSection>

          <ProjectSection id="limitations">
            <ul className="list-disc space-y-1.5 pl-5">
              <li>
                The scripted agent reads keywords and product names. It handles the scenarios it was
                written for and simple variations; anything else gets a clarifying question or a
                hand-over.
              </li>
              <li>
                Models have not been scored on this server yet, because none is configured by
                default. The suite is ready to run when a key is.
              </li>
              <li>
                Shipments and the policy are simulated, and credit notes in the source data do not
                reference the invoice they credit, so the agent cannot check for an earlier refund
                on the same items.
              </li>
              <li>
                Each conversation is one customer; there is no login. The customer is chosen in the
                demo, which a real system would take from an authenticated session.
              </li>
            </ul>
          </ProjectSection>

          <ProjectSection id="source">
            <p>The full source is on GitHub under the MIT licence, with the tests and scenarios.</p>
            <ul className="space-y-2">
              {(
                [
                  ["agent.py", "The agent loop, budgets, hand-over and approval resume"],
                  ["tools.py", "The eight tools and their argument models"],
                  ["refunds.py", "Refund rules"],
                  ["scripted.py", "The scripted agent used without a model"],
                  ["shipments.py", "Simulated shipments"],
                  ["policy.py", "The written policy and its indexing"],
                  ["scenarios.py", "The customer scenarios"],
                  ["evaluation.py", "Scenario checks"],
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
