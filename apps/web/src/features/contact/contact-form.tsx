"use client";

import Link from "next/link";
import { useId, useState, type FormEvent } from "react";

import { buttonClasses } from "@/components/button-link";
import { site } from "@/lib/site";

const topics = [
  ["full_time", "A full-time role"],
  ["contract", "A contract"],
  ["project", "A fixed-scope project"],
  ["consulting", "Advice or a review"],
  ["other", "Something else"],
] as const;

type Field = "name" | "email" | "company" | "topic" | "message";
type State =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent" }
  | { kind: "error"; message: string; fields: Partial<Record<Field, string>> };

const fieldMessages: Record<Field, string> = {
  name: "Enter your name on one line.",
  email: "Enter an email address I can reply to.",
  company: "Keep the company name on one line, under 120 characters.",
  topic: "Choose what you would like to talk about.",
  message: "Write at least 20 characters, so I know what you need.",
};

interface ValidationProblem {
  code?: string;
  detail?: string;
  errors?: { loc: (string | number)[] }[];
}

async function send(form: HTMLFormElement): Promise<State> {
  const data = new FormData(form);
  const body = {
    name: String(data.get("name") ?? ""),
    email: String(data.get("email") ?? ""),
    company: String(data.get("company") ?? "") || null,
    topic: String(data.get("topic") ?? "project"),
    message: String(data.get("message") ?? ""),
    website: String(data.get("website") ?? "") || null,
  };
  let res: Response;
  try {
    res = await fetch("/api/contact", {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return {
      kind: "error",
      message: `The message could not be sent. Check your connection, or email ${site.email} directly.`,
      fields: {},
    };
  }
  if (res.ok) return { kind: "sent" };
  const problem = (await res.json().catch(() => ({}))) as ValidationProblem;
  if (res.status === 422 && problem.errors) {
    const fields: Partial<Record<Field, string>> = {};
    for (const e of problem.errors) {
      const f = e.loc[e.loc.length - 1];
      if (typeof f === "string" && f in fieldMessages)
        fields[f as Field] = fieldMessages[f as Field];
    }
    return { kind: "error", message: "Some fields need another look.", fields };
  }
  if (res.status === 429) {
    return {
      kind: "error",
      message: `You have sent several messages already today. Please email ${site.email} instead.`,
      fields: {},
    };
  }
  return {
    kind: "error",
    message: `The form is not working right now. Please email ${site.email} directly.`,
    fields: {},
  };
}

const inputClass =
  "mt-1.5 block w-full rounded-sm bg-ink px-3 py-2.5 text-text ring-1 ring-inset ring-line-strong " +
  "placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-link aria-[invalid=true]:ring-fail";

export function ContactForm() {
  const [state, setState] = useState<State>({ kind: "idle" });
  const id = useId();
  const fieldError = (f: Field) => (state.kind === "error" ? state.fields[f] : undefined);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setState({ kind: "sending" });
    setState(await send(e.currentTarget));
  };

  if (state.kind === "sent") {
    return (
      <div role="status" className="rounded-md border border-pass/40 bg-pass/5 p-6">
        <p className="font-semibold text-pass">Message sent.</p>
        <p className="mt-1 text-muted">Thank you. The reply will come from {site.email}.</p>
      </div>
    );
  }

  const field = (name: Field, label: string, input: React.ReactNode, hint?: string) => {
    const err = fieldError(name);
    return (
      <div>
        <label htmlFor={`${id}-${name}`} className="text-sm font-medium text-text">
          {label}
          {hint && <span className="font-normal text-faint"> {hint}</span>}
        </label>
        {input}
        {err && (
          <p id={`${id}-${name}-err`} className="mt-1 text-sm text-fail">
            {err}
          </p>
        )}
      </div>
    );
  };

  const aria = (name: Field) => ({
    id: `${id}-${name}`,
    name,
    "aria-invalid": fieldError(name) ? true : undefined,
    "aria-describedby": fieldError(name) ? `${id}-${name}-err` : undefined,
  });

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-2">
        {field(
          "name",
          "Name",
          <input
            {...aria("name")}
            required
            maxLength={120}
            autoComplete="name"
            className={inputClass}
          />,
        )}
        {field(
          "email",
          "Email",
          <input
            {...aria("email")}
            type="email"
            required
            maxLength={320}
            autoComplete="email"
            className={inputClass}
          />,
        )}
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        {field(
          "company",
          "Company",
          <input
            {...aria("company")}
            maxLength={120}
            autoComplete="organization"
            className={inputClass}
          />,
          "(optional)",
        )}
        {field(
          "topic",
          "What it is about",
          <select {...aria("topic")} defaultValue="full_time" className={inputClass}>
            {topics.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>,
        )}
      </div>
      {field(
        "message",
        "Message",
        <textarea
          {...aria("message")}
          required
          minLength={20}
          maxLength={4000}
          rows={6}
          placeholder="The problem, the data or systems involved, and any timeline."
          className={inputClass}
        />,
      )}
      {/* Honeypot: hidden from people and assistive technology, filled in by naive bots. */}
      <div aria-hidden className="absolute -left-[9999px] h-px w-px overflow-hidden">
        <label htmlFor={`${id}-website`}>Website</label>
        <input id={`${id}-website`} name="website" tabIndex={-1} autoComplete="off" />
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <button
          type="submit"
          className={buttonClasses("primary", "md")}
          disabled={state.kind === "sending"}
        >
          {state.kind === "sending" ? "Sending…" : "Send message"}
        </button>
        <p className="text-sm text-faint">
          Stored only to reply to you. See the{" "}
          <Link href="/privacy" className="underline">
            privacy notice
          </Link>
          .
        </p>
      </div>
      <div aria-live="polite">
        {state.kind === "error" && <p className="text-sm text-fail">{state.message}</p>}
      </div>
    </form>
  );
}
