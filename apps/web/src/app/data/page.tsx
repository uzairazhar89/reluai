import type { Metadata } from "next";
import Link from "next/link";

import { Pill } from "@/components/status-badge";
import { projects } from "@/content/projects";
import { formatInt } from "@/lib/format";
import { loadManifest, type ManifestDataset } from "@/lib/manifest";

// Rendered once at build time from artifacts/manifest.yaml.
export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Data and licences",
  description:
    "Every dataset used by the demos on this site: source, licence, attribution, what was " +
    "changed and how each download is verified.",
  alternates: { canonical: "/data" },
};

const projectTitle = (repoDir: string) =>
  projects.find((p) => p.repoPath === `projects/${repoDir}`)?.title ?? repoDir;

function Dataset({ d }: { d: ManifestDataset }) {
  const canonical = d.sources.find((s) => s.role === "canonical");
  const mirrors = d.sources.filter((s) => s.role === "mirror");
  return (
    <article id={d.id} className="scroll-mt-24 border-t border-line pt-8">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="heading text-xl">{d.title}</h2>
        <Pill tone={d.real_data ? "pass" : "warn"}>
          {d.real_data ? "Real data" : "Synthetic data"}
        </Pill>
      </div>
      <p className="mt-1 text-sm text-muted">
        {d.publisher}
        {d.doi ? (
          <>
            , DOI{" "}
            <a href={`https://doi.org/${d.doi}`} className="prose-link">
              {d.doi}
            </a>
          </>
        ) : null}
      </p>

      <dl className="mt-6 space-y-5 text-muted">
        <div>
          <dt className="font-medium text-text">What it is</dt>
          <dd className="mt-1 max-w-[70ch]">{d.description}</dd>
        </div>
        <div>
          <dt className="font-medium text-text">Licence and attribution</dt>
          <dd className="mt-1 max-w-[70ch] space-y-2">
            <p>
              <a href={d.licence.url} className="prose-link">
                {d.licence.name}
              </a>
              . {d.licence.attribution}
            </p>
            {d.licence.notes && <p className="text-sm">{d.licence.notes}</p>}
          </dd>
        </div>
        {d.modifications && d.modifications.length > 0 && (
          <div>
            <dt className="font-medium text-text">What was changed</dt>
            <dd className="mt-1 max-w-[70ch]">
              <ul className="list-disc space-y-1 pl-5">
                {d.modifications.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        <div>
          <dt className="font-medium text-text">How downloads are verified</dt>
          <dd className="mt-1 max-w-[70ch] space-y-2">
            <p>
              The data is not stored in the repository. It is downloaded when the server image is
              built and accepted only if it has{" "}
              {d.checks.rows ? `exactly ${formatInt(d.checks.rows)} rows, ` : ""}
              {d.checks.columns ? `the expected ${d.checks.columns.length} columns, ` : ""}
              {d.checks.min_timestamp && d.checks.max_timestamp
                ? `timestamps from ${d.checks.min_timestamp.replace("T", " ")} to ${d.checks.max_timestamp.replace("T", " ")}, `
                : ""}
              and a content fingerprint matching the one recorded here.
            </p>
            {d.checks.content_sha256 && (
              <p className="break-all font-mono text-xs text-faint">
                fingerprint sha256 {d.checks.content_sha256}
              </p>
            )}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-text">Sources</dt>
          <dd className="mt-1 max-w-[70ch]">
            <ul className="space-y-2">
              {canonical && (
                <li>
                  Primary:{" "}
                  <a href={d.homepage} className="prose-link">
                    {d.publisher}
                  </a>
                  {canonical.notes ? `. ${canonical.notes}` : ""}
                </li>
              )}
              {mirrors.map((m) => (
                <li key={m.url}>
                  Fallback:{" "}
                  <a href={m.url} className="prose-link break-all">
                    pinned mirror
                  </a>
                  {m.notes ? `. ${m.notes}` : ""}
                </li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt className="font-medium text-text">Used by</dt>
          <dd className="mt-1">{d.used_by.map(projectTitle).join(", ")}</dd>
        </div>
      </dl>
    </article>
  );
}

export default function DataPage() {
  const manifest = loadManifest();
  return (
    <div className="mx-auto max-w-4xl px-5 pt-12 sm:px-8 md:pt-16">
      <h1 className="display text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">Data and licences</h1>
      <div className="mt-5 max-w-[66ch] space-y-4 text-lg text-muted">
        <p>
          The demos on this site run on public data. This page lists every dataset, where it comes
          from, its licence, and exactly what was changed.
        </p>
      </div>

      <section
        aria-labelledby="rules-h"
        className="mt-10 rounded-md border border-line bg-surface p-6"
      >
        <h2 id="rules-h" className="heading text-lg">
          Rules every demo follows
        </h2>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted">
          <li>
            Real data is shown with its real dates and values. Nothing is shifted to look recent.
          </li>
          <li>
            Simulated faults and synthetic data are always labelled as such where they appear.
          </li>
          <li>
            People are never identifiable: customer IDs stay anonymous, and faces and licence plates
            in video are blurred.
          </li>
          <li>
            Organisations are never named next to an automated judgement; stable codes are used
            instead.
          </li>
          <li>Figures on the site come from recorded runs on this server, not from estimates.</li>
        </ul>
      </section>

      <div className="mt-12 space-y-12">
        {manifest.datasets.map((d) => (
          <Dataset key={d.id} d={d} />
        ))}
      </div>

      <p className="mt-12 text-sm text-faint">
        New datasets are added here when the project that uses them goes live. The record is
        generated from the repository&apos;s artifact manifest, the same file the download
        verification reads. See also the{" "}
        <Link href="/privacy" className="prose-link">
          privacy notice
        </Link>
        .
      </p>
    </div>
  );
}
