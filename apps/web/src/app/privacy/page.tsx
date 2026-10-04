import type { Metadata } from "next";

import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What reluai.cloud records when you visit, use a demo or send a message, and for how long.",
  alternates: { canonical: "/privacy" },
};

const sections = [
  [
    "No tracking",
    "There are no cookies, analytics, advertising or third-party scripts on this site. Fonts are served from this server, so your browser does not contact any other service.",
  ],
  [
    "Server logs",
    "The web server records each request (IP address, time, page, browser identification and response) to diagnose faults and stop abuse. Logs rotate automatically: each service keeps at most 30 MB, and older entries are overwritten.",
  ],
  [
    "Demo usage limits",
    "To share the server fairly, demos limit how often each visitor can start a job. Your IP address is not stored for this: it is combined with a secret key into a short code that changes every day and cannot be turned back into the address. Usage counters are deleted daily once their time window has ended.",
  ],
  [
    "Demo runs",
    "When you start a pipeline run, the run and its results are stored and shown publicly on the dashboard, labelled only as started by a visitor. The run keeps the daily usage code described above, which is never shown, and nothing else about you.",
  ],
  [
    "Contact form",
    "Messages you send (name, email, optional company, topic and message) are stored in this site's database so I can reply. They are not shared with anyone, and are deleted automatically after 12 months; database backups that may contain them are kept for at most 5 weeks after that. Ask me to delete yours sooner and I will.",
  ],
  [
    "AI demos",
    "None of the live demos send your input to an AI provider. Before any demo does, this page will say which provider receives what, and the demo will say so where you type.",
  ],
] as const;

export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-3xl px-5 pt-12 sm:px-8 md:pt-16">
      <h1 className="display text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">Privacy</h1>
      <p className="mt-5 max-w-[62ch] text-lg text-muted">
        This site is a personal portfolio run by {site.name}. It collects as little as it can, and
        this page lists all of it.
      </p>
      <dl className="mt-10 space-y-7">
        {sections.map(([term, desc]) => (
          <div key={term} className="border-t border-line pt-4">
            <dt className="font-semibold text-text">{term}</dt>
            <dd className="mt-1.5 max-w-[66ch] text-muted">{desc}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-10 text-muted">
        Questions or deletion requests:{" "}
        <a href={`mailto:${site.email}`} className="prose-link">
          {site.email}
        </a>
        .
      </p>
      <p className="mt-3 text-sm text-faint">Last updated 4 October 2026.</p>
    </div>
  );
}
