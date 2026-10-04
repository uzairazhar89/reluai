import Link from "next/link";

import type { Project } from "@/content/projects";
import { statusLabel } from "@/content/projects";
import { site } from "@/lib/site";

import { Pill } from "./status-badge";

export function ProjectCard({ project }: { project: Project }) {
  const href = `/projects/${project.slug}`;
  return (
    <article className="flex flex-col rounded-md border border-line bg-surface p-6">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone="pass">{statusLabel[project.status]}</Pill>
        {project.roles.map((r) => (
          <Pill key={r}>{r}</Pill>
        ))}
      </div>
      <h3 className="heading mt-4 text-xl">
        <Link href={href} className="hover:underline hover:underline-offset-4">
          {project.title}
        </Link>
      </h3>
      <dl className="mt-5 space-y-4 text-sm">
        <div>
          <dt className="font-semibold">Problem</dt>
          <dd className="mt-1 text-muted">{project.problem}</dd>
        </div>
        <div>
          <dt className="font-semibold">Solution</dt>
          <dd className="mt-1 text-muted">{project.solution}</dd>
        </div>
        <div>
          <dt className="font-semibold">Technologies</dt>
          <dd className="mt-2">
            <ul className="flex flex-wrap gap-1.5">
              {project.tech.map((t) => (
                <li key={t} className="rounded-sm bg-surface-2 px-2 py-0.5 text-xs text-muted">
                  {t}
                </li>
              ))}
            </ul>
          </dd>
        </div>
      </dl>
      {project.dataNote && <p className="mt-5 text-xs text-faint">{project.dataNote}</p>}
      <div className="mt-auto flex flex-wrap gap-x-6 gap-y-2 pt-6 text-sm">
        <Link href={`${href}#demo`} className="prose-link">
          Live demo
        </Link>
        <Link href={`${href}#architecture`} className="prose-link">
          Architecture
        </Link>
        <a href={`${site.repo}/tree/main/${project.repoPath}`} className="prose-link">
          GitHub
        </a>
      </div>
    </article>
  );
}
