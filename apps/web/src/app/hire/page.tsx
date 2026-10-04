import type { Metadata } from "next";
import Link from "next/link";

import { ContactForm } from "@/features/contact/contact-form";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Hire me",
  description:
    "Hire Uzair Azhar for Python, data engineering, AI application or computer-vision work: " +
    "full-time roles, contracts and fixed-scope projects.",
  alternates: { canonical: "/hire" },
};

const engagements = [
  [
    "Full-time roles and contracts",
    "Python, data engineering, AI application and computer-vision roles where one engineer can own a system end to end, from the data model to the deployment.",
  ],
  [
    "Fixed-scope projects",
    "A written problem statement and estimate first, a working version you can run within the first week or two, then increments with a demo each week. Handover includes tests, deployment and documentation.",
  ],
  [
    "Reviews and advice",
    "A second pair of eyes on a pipeline, an LLM feature or a deployment: what will break first, and what to fix in which order.",
  ],
] as const;

const evidence = [
  {
    href: "/projects/data-pipeline-observatory",
    label: "A live data pipeline with its tests and results",
    internal: true,
  },
  {
    href: site.repo,
    label: "The full source of this site and its infrastructure",
    internal: false,
  },
  { href: "/#research", label: "Research: a medical-imaging paper under review", internal: true },
] as const;

export default function HirePage() {
  return (
    <div className="mx-auto max-w-6xl px-5 pt-12 sm:px-8 md:pt-16">
      <div className="grid gap-14 lg:grid-cols-[5fr_6fr]">
        <div>
          <h1 className="display text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">Hire me</h1>
          <p className="mt-5 max-w-[56ch] text-lg text-muted">
            I build Python systems that turn messy data and documents into something a business can
            rely on, and I deploy and maintain them myself. Tell me about the problem; I will tell
            you honestly whether I am the right person for it.
          </p>

          <dl className="mt-10 space-y-6">
            {engagements.map(([term, desc]) => (
              <div key={term} className="border-t border-line pt-4">
                <dt className="font-semibold text-text">{term}</dt>
                <dd className="mt-1 text-muted">{desc}</dd>
              </div>
            ))}
          </dl>

          <h2 className="heading mt-12 text-lg">Before you write, you can check</h2>
          <ul className="mt-3 space-y-2">
            {evidence.map((e) => (
              <li key={e.href}>
                {e.internal ? (
                  <Link href={e.href} className="prose-link">
                    {e.label}
                  </Link>
                ) : (
                  <a href={e.href} className="prose-link">
                    {e.label}
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>

        <section
          aria-labelledby="contact-h"
          className="rounded-md border border-line bg-surface p-6 sm:p-8"
        >
          <h2 id="contact-h" className="heading text-xl">
            Send a message
          </h2>
          <p className="mt-2 text-muted">
            Or email{" "}
            <a href={`mailto:${site.email}`} className="prose-link">
              {site.email}
            </a>{" "}
            directly, or find me on{" "}
            <a href={site.linkedin} className="prose-link" rel="me">
              LinkedIn
            </a>
            .
          </p>
          <div className="mt-7">
            <ContactForm />
          </div>
        </section>
      </div>
    </div>
  );
}
