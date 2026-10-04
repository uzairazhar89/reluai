import type { Metadata } from "next";

import { ProjectCard } from "@/components/project-card";
import { Pill } from "@/components/status-badge";
import { liveProjects, statusLabel, upcomingProjects } from "@/content/projects";

export const metadata: Metadata = {
  title: "Projects",
  description:
    "Engineering projects with live demos on real data: data pipelines, AI applications and " +
    "computer vision, each with architecture, results and source code.",
  alternates: { canonical: "/projects" },
};

export default function ProjectsPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 pt-12 sm:px-8 md:pt-16">
      <h1 className="display text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">Projects</h1>
      <p className="mt-5 max-w-[62ch] text-lg text-muted">
        Each project solves a problem businesses actually have, runs live on this site and is
        written up with its architecture, measured results, failure handling, cost and limitations.
      </p>

      <section aria-labelledby="live-h" className="mt-14">
        <h2 id="live-h" className="heading text-xl">
          Live now
        </h2>
        <div
          className={`mt-6 grid gap-6 ${liveProjects.length > 1 ? "lg:grid-cols-2" : "max-w-2xl"}`}
        >
          {liveProjects.map((p) => (
            <ProjectCard key={p.slug} project={p} />
          ))}
        </div>
      </section>

      <section aria-labelledby="next-h" className="mt-16">
        <h2 id="next-h" className="heading text-xl">
          In build and planned
        </h2>
        <p className="mt-2 max-w-[62ch] text-muted">
          These have no page or demo until they work end to end on real or clearly labelled data.
          They are released in this order.
        </p>
        <ol className="mt-6 divide-y divide-line border-y border-line">
          {upcomingProjects.map((p, i) => (
            <li key={p.slug} className="grid gap-x-6 gap-y-2 py-4 sm:grid-cols-[2rem_1fr_auto]">
              <span className="num hidden text-faint sm:block">{i + 2}</span>
              <div>
                <h3 className="font-semibold text-text">{p.title}</h3>
                <p className="mt-0.5 text-muted">{p.oneLiner}</p>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {p.roles.map((r) => (
                    <li key={r} className="rounded-sm bg-surface-2 px-2 py-0.5 text-xs text-muted">
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="sm:pt-0.5">
                <Pill tone={p.status === "building" ? "warn" : "neutral"}>
                  {statusLabel[p.status]}
                </Pill>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
