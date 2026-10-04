import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { serverGet } from "@/lib/api/server";
import type { Scenario, SiteStatus, Summary } from "@/lib/api/types";
import { formatDateTime, formatDropKey, formatDuration, formatRelative } from "@/lib/format";

export const revalidate = 30;

export const metadata: Metadata = {
  title: "Status",
  description: "Live status of the services behind reluai.cloud and the most recent pipeline runs.",
  alternates: { canonical: "/status" },
};

const headline: Record<string, string> = {
  operational: "All systems operational",
  degraded: "Some systems are degraded",
  down: "A system is down",
};

export default async function StatusPage() {
  const [status, summary, scenarios] = await Promise.all([
    serverGet<SiteStatus>("/api/status", revalidate),
    serverGet<Summary>("/api/pipeline/summary", revalidate),
    serverGet<Scenario[]>("/api/pipeline/scenarios", 3600),
  ]);
  const scenarioTitle = (id: string) =>
    (scenarios.ok ? scenarios.data.find((x) => x.id === id)?.title : undefined) ??
    id.replaceAll("_", " ");
  const checkedAt = status.ok ? status.data.checked_at : new Date().toISOString();
  const overall = status.ok ? status.data.status : "down";

  const components = [
    { name: "Website", status: "operational", detail: "Serving this page" },
    ...(status.ok
      ? status.data.components
      : [{ name: "API", status: "down", detail: "Not reachable from the website" }]),
  ];

  return (
    <div className="mx-auto max-w-3xl px-5 pt-12 sm:px-8 md:pt-16">
      <h1 className="display text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">Status</h1>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface p-5">
        <p className="heading text-lg">{headline[overall] ?? overall}</p>
        <p className="text-sm text-muted">
          Checked {formatDateTime(checkedAt)}
          {status.ok ? `, version ${status.data.version}` : ""}
        </p>
      </div>

      <ul className="mt-6 divide-y divide-line border-y border-line">
        {components.map((c) => (
          <li key={c.name} className="flex items-start justify-between gap-4 py-4">
            <div>
              <p className="font-medium text-text">{c.name}</p>
              <p className="text-sm text-muted">{c.detail}</p>
            </div>
            <StatusBadge status={c.status} />
          </li>
        ))}
      </ul>
      {status.ok && status.data.busy_with && (
        <p className="mt-3 text-sm text-muted">
          The worker is currently running: {status.data.busy_with}.
        </p>
      )}

      {summary.ok && summary.data.trend.length > 0 && (
        <section aria-labelledby="runs-h" className="mt-14">
          <h2 id="runs-h" className="heading text-xl">
            Recent pipeline runs
          </h2>
          <p className="mt-2 text-muted">
            Scheduled runs every 6 hours, plus runs started by visitors.{" "}
            <Link href="/projects/data-pipeline-observatory#demo" className="prose-link">
              Open the dashboard
            </Link>
            .
          </p>
          <ol className="mt-5 divide-y divide-line/60">
            {[...summary.data.trend]
              .reverse()
              .slice(0, 12)
              .map((p) => (
                <li
                  key={p.id}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 text-sm"
                >
                  <span className="text-text">
                    {formatDropKey(p.drop_key)}
                    <span className="text-muted">, {scenarioTitle(p.scenario)}</span>
                  </span>
                  <span className="flex items-center gap-4">
                    <span className="num text-muted">{formatDuration(p.duration_ms)}</span>
                    <span className="text-faint">{formatRelative(p.started_at)}</span>
                    <StatusBadge status={p.status} />
                  </span>
                </li>
              ))}
          </ol>
        </section>
      )}

      <section aria-labelledby="how-h" className="mt-14 text-muted">
        <h2 id="how-h" className="heading text-xl text-text">
          What is checked
        </h2>
        <p className="mt-3">
          This page asks the API whether it can reach the database and when the pipeline last
          finished a run. The pipeline counts as degraded if no run has finished in 13 hours, since
          runs are scheduled every 6.
        </p>
        <p className="mt-3">
          Each deployment must also pass a readiness check (database reachable, schema at the
          expected migration, free disk space) and serve both the API and this website through
          nginx. If any of those fail, the previous version is restored automatically.
        </p>
        <p className="mt-3 text-sm text-faint">This page refreshes at most every 30 seconds.</p>
      </section>
    </div>
  );
}
