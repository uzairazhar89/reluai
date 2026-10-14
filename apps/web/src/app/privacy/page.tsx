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
    "CSV analyst: uploads",
    "A file you upload to the AI CSV Analyst is stored only on this server, in temporary storage inside the application, and deleted one hour after upload (or when the service restarts, if sooner). Its contents are never logged and never shown to anyone else; only you have its random link.",
  ],
  [
    "CSV analyst: questions",
    "Questions are answered on this server. For each one, only the outcome is recorded (answered or not, by rules or a model, timings and row count) so the page can show usage figures; the question text is not stored.",
  ],
  [
    "Support agent: conversations",
    "Messages you type in the Customer Support Agent demo, the agent's steps and the simulated refunds and tickets are stored with the conversation for 24 hours so the page can show the trace, then deleted. The conversation keeps the daily usage code described above, so only you can continue it; nothing else about you is stored.",
  ],
  [
    "Document Intelligence: uploads for questions",
    "A PDF you upload is held in memory on this server only until it has been read (seconds), then discarded; it is never written to disk. The text and passages extracted from it are stored in the database for one hour so you can ask questions, then deleted, or at once if you press Delete now. The document keeps the daily usage code described above, so only you can open it. Its contents and your questions are never logged; only counts and timings are.",
  ],
  [
    "Document Intelligence: invoices",
    "An invoice PDF you upload to be read is processed in memory on this server, in a separate process, and only the extracted fields are sent back to your browser; the file and the result are not stored or logged (only page and line counts and timings are). Reading a sample invoice is counted against the hourly limit with the daily usage code described above.",
  ],
  [
    "AI providers",
    "Questions about the retailer table that the rule-based parser cannot read may be sent to a language model provider (Groq, or Cerebras as a fallback) with the table's column names, types and example values, when one is configured. For your own uploads this happens only if you tick the box that allows it, and then only your question and the file's column names and types are sent, never its rows. In the support agent demo, when a provider is configured, the conversation (your messages, the anonymised invoice details the agent looks up and the demo's policy text) is sent to it to choose the next step. In the Document Intelligence demo, questions about the sample document may be answered by a provider with the retrieved passages; for a PDF you uploaded, your question and up to six retrieved passages (never the whole file) are sent only if you tick the box that allows it. Invoices are read without any provider. Each page says when no provider is configured. Providers' own terms govern what they keep.",
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
