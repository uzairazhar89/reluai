import { ButtonLink } from "@/components/button-link";
import { JsonLd } from "@/components/json-ld";
import { LiveRunPanel } from "@/components/live-run-panel";
import { ProjectCard } from "@/components/project-card";
import { Pill } from "@/components/status-badge";
import { liveProjects, statusLabel, upcomingProjects } from "@/content/projects";
import { serverGet } from "@/lib/api/server";
import type { RunDetail, Summary } from "@/lib/api/types";
import { site } from "@/lib/site";

// Rebuilt at most once a minute, so the live panel shows real, recent figures without
// shipping client-side JavaScript for it.
export const revalidate = 60;

const whatIBuild = [
  [
    "Python data pipelines",
    "Ingestion from files, databases and APIs, with validation, retries and audit trails.",
  ],
  [
    "AI and LLM applications",
    "Question answering over documents, natural-language interfaces to data, tool-calling agents.",
  ],
  ["Computer vision", "Detection, tracking and image analysis, optimised to run on ordinary CPUs."],
  ["Automation", "Replacing manual spreadsheet and inbox work with scheduled, observable jobs."],
  [
    "APIs and backend systems",
    "FastAPI services with typed contracts, migrations and sensible limits.",
  ],
  [
    "Dockerised deployments",
    "Reproducible builds, health checks and rollbacks on a single VPS or the cloud.",
  ],
  [
    "Data processing",
    "Cleaning, reconciling and profiling messy tabular data at millions of rows.",
  ],
  [
    "Research and scientific AI",
    "Medical-imaging models and literature tooling, written up properly.",
  ],
] as const;

const capabilities = [
  [
    "Languages and data",
    ["Python", "SQL", "pandas", "DuckDB", "PostgreSQL", "pgvector", "JSON / CSV"],
  ],
  ["Backend", ["FastAPI", "Pydantic", "SQLAlchemy", "Alembic", "REST APIs", "job queues"]],
  [
    "Machine learning",
    ["PyTorch", "ONNX Runtime", "quantisation", "computer vision", "medical imaging"],
  ],
  ["LLM systems", ["RAG", "embeddings", "function calling", "Groq", "llama.cpp"]],
  [
    "Delivery",
    ["Docker", "Linux", "nginx", "Git", "GitHub Actions", "Ansible", "TypeScript / Next.js"],
  ],
] as const;

const process = [
  [
    "Problem",
    "A written statement of what goes wrong today, who notices and what fixing it is worth.",
  ],
  [
    "Architecture",
    "The smallest design that solves it, with the trade-offs written down before any code.",
  ],
  ["Implementation", "Typed, reviewed code in small increments you can run from the first week."],
  [
    "Testing",
    "Automated tests on every change, including checks against real data where it exists.",
  ],
  [
    "Deployment",
    "Container images built and scanned in CI, released with a health check and automatic rollback.",
  ],
  [
    "Monitoring",
    "Structured logs, health checks and alerts, so problems are noticed before users report them.",
  ],
] as const;

export default async function HomePage() {
  const renderedAt = new Date().toISOString();
  const summary = await serverGet<Summary>("/api/pipeline/summary", revalidate);
  const lastId = summary.ok ? summary.data.last_run?.id : undefined;
  const detail = lastId
    ? await serverGet<RunDetail>(`/api/pipeline/runs/${lastId}`, revalidate)
    : null;

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "Person",
          name: site.name,
          url: site.url,
          email: `mailto:${site.email}`,
          jobTitle: "Python, data and AI engineer",
          sameAs: [site.github, site.linkedin],
          knowsAbout: ["Python", "Data engineering", "ETL", "Computer vision", "RAG", "FastAPI"],
        }}
      />

      {/* Hero */}
      <section className="mx-auto grid max-w-6xl gap-12 px-5 pb-20 pt-16 sm:px-8 md:pt-24 lg:grid-cols-[7fr_5fr] lg:items-start">
        <div>
          <p className="text-base text-muted">Uzair Azhar, Python and AI engineer</p>
          <h1 className="display mt-4 text-[2.15rem] leading-[1.06] sm:text-3xl xl:text-[2.85rem]">
            Data, AI and computer-vision systems that are deployed, measured and maintained.
          </h1>
          <p className="mt-6 max-w-[60ch] text-lg text-muted">
            I take a messy, real problem, such as unreliable data feeds or documents nobody can
            search, and ship the system that solves it, with the tests, monitoring and documentation
            that keep it running after handover.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <ButtonLink href="/projects">View projects</ButtonLink>
            <ButtonLink href="/hire" variant="secondary">
              Hire me
            </ButtonLink>
            <ButtonLink href={site.github} variant="secondary" external>
              GitHub
            </ButtonLink>
          </div>
        </div>
        <LiveRunPanel
          summary={summary.ok ? summary.data : null}
          detail={detail?.ok ? detail.data : null}
          renderedAt={renderedAt}
        />
      </section>

      {/* Projects */}
      <section
        id="projects"
        aria-labelledby="projects-h"
        className="mx-auto max-w-6xl px-5 py-16 sm:px-8"
      >
        <h2 id="projects-h" className="heading text-2xl">
          Selected engineering projects
        </h2>
        <p className="mt-3 max-w-[64ch] text-muted">
          Each project has a working demo on real or clearly labelled data, a write-up of the design
          decisions, and its source code.
        </p>
        <div className="mt-10 grid gap-6 lg:grid-cols-2 lg:items-start">
          {liveProjects.map((p) => (
            <ProjectCard key={p.slug} project={p} />
          ))}
          <div className="rounded-md border border-dashed border-line p-6">
            <h3 className="text-base font-semibold">Next on the roadmap</h3>
            <p className="mt-1 text-sm text-muted">
              Listed honestly: these are not live yet and have no demo until they are.
            </p>
            <ul className="mt-5 divide-y divide-line">
              {upcomingProjects.map((p) => (
                <li key={p.slug} className="flex items-start justify-between gap-4 py-3">
                  <div>
                    <p className="text-sm font-medium">{p.title}</p>
                    <p className="text-sm text-muted">{p.oneLiner}</p>
                  </div>
                  <Pill tone={p.status === "building" ? "warn" : "neutral"}>
                    {statusLabel[p.status]}
                  </Pill>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* What I build */}
      <section aria-labelledby="build-h" className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <h2 id="build-h" className="heading text-2xl">
          What I build
        </h2>
        <dl className="mt-8 grid gap-x-12 gap-y-6 sm:grid-cols-2">
          {whatIBuild.map(([term, desc]) => (
            <div key={term} className="border-t border-line pt-4">
              <dt className="font-semibold">{term}</dt>
              <dd className="mt-1 text-muted">{desc}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Capabilities */}
      <section aria-labelledby="cap-h" className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <h2 id="cap-h" className="heading text-2xl">
          Engineering capabilities
        </h2>
        <div className="mt-8 space-y-5">
          {capabilities.map(([group, items]) => (
            <div key={group} className="grid gap-2 sm:grid-cols-[13rem_1fr] sm:items-baseline">
              <p className="text-sm text-muted">{group}</p>
              <ul className="flex flex-wrap gap-2">
                {items.map((item) => (
                  <li
                    key={item}
                    className="rounded-sm bg-surface px-2.5 py-1 text-sm ring-1 ring-inset ring-line"
                  >
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Research */}
      <section
        id="research"
        aria-labelledby="research-h"
        className="mx-auto max-w-6xl scroll-mt-20 px-5 py-16 sm:px-8"
      >
        <h2 id="research-h" className="heading text-2xl">
          Research and specialised work
        </h2>
        <div className="mt-8 grid gap-8 lg:grid-cols-[2fr_1fr]">
          <article className="border-l-2 border-pass/60 pl-6">
            <p className="text-sm text-muted">Medical imaging, skin-lesion classification</p>
            <h3 className="mt-2 text-lg font-semibold leading-snug">
              SHEL: A Knowledge-Guided Hybrid Representation Learning Framework for Efficient
              Multiclass Skin Lesion Classification
            </h3>
            <p className="mt-3 text-muted">
              Manuscript under review at a Springer Nature journal. Details and results will be
              linked here once it is published.
            </p>
          </article>
          <p className="text-sm text-muted">
            Related work on this site: research-literature search with medical terminology (Research
            Search Intelligence) and computer vision on video (Street Scene Intelligence), both on
            the roadmap.
          </p>
        </div>
      </section>

      {/* How I work */}
      <section
        id="how-i-work"
        aria-labelledby="how-h"
        className="mx-auto max-w-6xl px-5 py-16 sm:px-8"
      >
        <h2 id="how-h" className="heading text-2xl">
          How I work
        </h2>
        <ol className="mt-8 grid gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
          {process.map(([step, desc], i) => (
            <li key={step} className="flex gap-4">
              <span className="num display mt-0.5 text-lg text-faint" aria-hidden>
                {i + 1}
              </span>
              <div>
                <p className="font-semibold">{step}</p>
                <p className="mt-1 text-sm text-muted">{desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Contact */}
      <section aria-labelledby="contact-h" className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <div className="rounded-md border border-line bg-surface px-6 py-10 sm:px-10">
          <h2 id="contact-h" className="heading text-2xl">
            Have a data or AI problem that needs to work in production?
          </h2>
          <p className="mt-3 max-w-[60ch] text-muted">
            Freelance projects, contracts and full-time roles. Send a short description of the
            problem and I will reply with questions or a first plan.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-4">
            <ButtonLink href="/hire">Start a conversation</ButtonLink>
            <a href={`mailto:${site.email}`} className="prose-link">
              {site.email}
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
