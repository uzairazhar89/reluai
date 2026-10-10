"use client";

import { useMemo, useState, type FormEvent } from "react";

import { buttonClasses } from "@/components/button-link";
import { QueryProvider } from "@/components/query-provider";
import { Pill } from "@/components/status-badge";
import type { Conversation, SupportCatalogue } from "@/lib/api/types";
import { useHydrated } from "@/lib/now";

import { Chat } from "./chat";
import { supportErrorMessage } from "./messages";
import { useCatalogue, useDecide, useReply, useStart } from "./queries";
import { Trace } from "./trace";

const reasonLabel: Record<string, string> = {
  damaged: "damaged items",
  missing_items: "missing items",
  late_delivery: "late delivery",
  lost_parcel: "lost parcel",
};

function money(x: number): string {
  return `£${x.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function Records({ conversation }: { conversation: Conversation }) {
  const { refunds, tickets } = conversation;
  if (refunds.length === 0 && tickets.length === 0) return null;
  return (
    <div className="grid gap-3 text-sm sm:grid-cols-2">
      {refunds.length > 0 && (
        <div>
          <p className="text-xs text-faint">Refunds recorded (simulated, nothing is paid)</p>
          <ul className="mt-1 space-y-1">
            {refunds.map((r, i) => (
              <li key={i} className="text-text">
                <span className="num">{money(r.amount_gbp)}</span> on {r.invoice_no},{" "}
                {reasonLabel[r.reason] ?? r.reason}, approved by {r.approved_by}
              </li>
            ))}
          </ul>
        </div>
      )}
      {tickets.length > 0 && (
        <div>
          <p className="text-xs text-faint">Tickets opened (simulated)</p>
          <ul className="mt-1 space-y-1">
            {tickets.map((t) => (
              <li key={t.id} className="text-text">
                <span className="font-mono text-xs">{t.id}</span> {t.category.replaceAll("_", " ")}
                {t.invoice_no ? ` for ${t.invoice_no}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ApprovalCard({
  conversation,
  onDecided,
}: {
  conversation: Conversation;
  onDecided: (c: Conversation) => void;
}) {
  const pending = conversation.approvals.find((a) => a.status === "pending");
  const decide = useDecide();
  const [note, setNote] = useState("");
  const hydrated = useHydrated();
  if (!pending) return null;
  const send = (decision: "approve" | "reject") =>
    decide.mutate(
      { id: conversation.id, decision, note: note.trim() || undefined },
      { onSuccess: onDecided },
    );
  return (
    <section
      aria-label="Refund waiting for approval"
      className="rounded-md p-4 ring-1 ring-inset ring-warn/50"
    >
      <p className="text-sm text-warn">You are the supervisor</p>
      <p className="mt-1 text-text">
        Refund <span className="num font-semibold">{money(pending.amount_gbp)}</span> on invoice{" "}
        {pending.invoice_no} for {reasonLabel[pending.reason] ?? pending.reason}? Refunds above £50
        need a person to approve them.
      </p>
      <label className="mt-3 block text-xs text-muted" htmlFor="approval-note">
        Note to the agent (optional)
      </label>
      <input
        id="approval-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={300}
        className="mt-1 h-9 w-full rounded-sm bg-ink px-3 text-sm text-text ring-1 ring-inset ring-line-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-link"
      />
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className={buttonClasses("primary", "sm")}
          disabled={!hydrated || decide.isPending}
          onClick={() => send("approve")}
        >
          Approve refund
        </button>
        <button
          type="button"
          className={buttonClasses("secondary", "sm")}
          disabled={!hydrated || decide.isPending}
          onClick={() => send("reject")}
        >
          Reject
        </button>
      </div>
      <div aria-live="polite" className="mt-2 min-h-5 text-sm">
        {decide.isPending && <p className="text-muted">The agent is following up…</p>}
        {decide.isError && <p className="text-fail">{supportErrorMessage(decide.error)}</p>}
      </div>
    </section>
  );
}

function Starter({
  catalogue,
  onStarted,
}: {
  catalogue: SupportCatalogue;
  onStarted: (c: Conversation) => void;
}) {
  const [mode, setMode] = useState<"scenario" | "own">("scenario");
  const [scenarioId, setScenarioId] = useState(catalogue.scenarios[0]?.id ?? "");
  const [customerId, setCustomerId] = useState(catalogue.customers[0]?.customer_id ?? 0);
  const [message, setMessage] = useState("");
  const start = useStart();
  const hydrated = useHydrated();
  const byCategory = useMemo(() => {
    const out = new Map<string, typeof catalogue.scenarios>();
    for (const s of catalogue.scenarios) out.set(s.category, [...(out.get(s.category) ?? []), s]);
    return out;
  }, [catalogue]);
  const scenario = catalogue.scenarios.find((s) => s.id === scenarioId);
  const customer = catalogue.customers.find((c) => c.customer_id === customerId);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mode === "scenario" && scenario)
      start.mutate({ scenario_id: scenario.id }, { onSuccess: onStarted });
    if (mode === "own" && message.trim().length >= 3)
      start.mutate({ customer_id: customerId, message: message.trim() }, { onSuccess: onStarted });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div role="radiogroup" aria-label="How to start" className="flex flex-wrap gap-2">
        {(
          [
            ["scenario", "Pick a customer scenario"],
            ["own", "Write your own message"],
          ] as const
        ).map(([value, label]) => (
          <label
            key={value}
            className={`cursor-pointer rounded-sm px-3 py-1.5 text-sm ring-1 ring-inset has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-link ${
              mode === value
                ? "bg-surface-2 text-text ring-line-strong"
                : "text-muted ring-line hover:text-text"
            }`}
          >
            <input
              type="radio"
              name="support-mode"
              value={value}
              checked={mode === value}
              onChange={() => setMode(value)}
              className="sr-only"
            />
            {label}
          </label>
        ))}
      </div>

      {mode === "scenario" ? (
        <div className="space-y-2">
          <label htmlFor="support-scenario" className="block text-sm font-semibold text-text">
            Scenario
          </label>
          <select
            id="support-scenario"
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
            className="h-10 w-full rounded-sm bg-ink px-3 text-sm text-text ring-1 ring-inset ring-line-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-link"
          >
            {[...byCategory.entries()].map(([category, items]) => (
              <optgroup key={category} label={category}>
                {items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {scenario && (
            <blockquote className="rounded-sm bg-surface-2 px-3.5 py-2.5 text-sm text-text">
              <span className="block text-xs text-faint">
                Customer {scenario.customer_id} writes
                {scenario.needs_supervisor ? "; you will decide on the refund" : ""}
              </span>
              {scenario.message}
            </blockquote>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <label htmlFor="support-customer" className="block text-sm font-semibold text-text">
            Customer
          </label>
          <select
            id="support-customer"
            value={customerId}
            onChange={(e) => setCustomerId(Number(e.target.value))}
            className="h-10 w-full rounded-sm bg-ink px-3 text-sm text-text ring-1 ring-inset ring-line-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-link"
          >
            {catalogue.customers.map((c) => (
              <option key={c.customer_id} value={c.customer_id}>
                {c.customer_id} ({c.country}, {c.invoices} orders)
              </option>
            ))}
          </select>
          {customer && (
            <p className="text-xs text-muted">
              Recent invoices:{" "}
              {customer.recent
                .map((r) => `${r.invoice_no} (${r.date}, ${money(r.total_gbp)})`)
                .join(", ")}
            </p>
          )}
          <label htmlFor="support-message" className="block pt-1 text-sm font-semibold text-text">
            Message as the customer
          </label>
          <textarea
            id="support-message"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={600}
            rows={3}
            placeholder="For example: two of the items on my last order arrived broken"
            className="w-full rounded-sm bg-ink px-3 py-2 text-sm text-text ring-1 ring-inset ring-line-strong placeholder:text-faint focus:outline-none focus-visible:ring-2 focus-visible:ring-link"
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className={buttonClasses("primary", "md")}
          disabled={!hydrated || start.isPending || (mode === "own" && message.trim().length < 3)}
        >
          {start.isPending ? "The agent is working…" : "Send to the agent"}
        </button>
        <span className="text-xs text-faint">
          {catalogue.llm_available
            ? "A free-tier model answers first; the scripted agent takes over if it is unavailable."
            : "No model is configured on this server, so the scripted agent answers."}
        </span>
      </div>
      <div aria-live="polite" className="min-h-5 text-sm">
        {start.isError && <p className="text-fail">{supportErrorMessage(start.error)}</p>}
      </div>
    </form>
  );
}

function FollowUp({
  conversation,
  onReplied,
}: {
  conversation: Conversation;
  onReplied: (c: Conversation) => void;
}) {
  const [text, setText] = useState("");
  const reply = useReply();
  const hydrated = useHydrated();
  if (!conversation.can_reply) return null;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim().length < 3) return;
        reply.mutate(
          { id: conversation.id, message: text.trim() },
          {
            onSuccess: (c) => {
              setText("");
              onReplied(c);
            },
          },
        );
      }}
      className="space-y-2"
    >
      <label htmlFor="support-reply" className="block text-sm text-muted">
        Reply as the customer
      </label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          id="support-reply"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={600}
          className="h-10 w-full min-w-0 rounded-sm bg-ink px-3 text-sm text-text ring-1 ring-inset ring-line-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-link sm:flex-1"
        />
        <button
          type="submit"
          className={buttonClasses("secondary", "sm")}
          disabled={!hydrated || reply.isPending || text.trim().length < 3}
        >
          {reply.isPending ? "Sending…" : "Send"}
        </button>
      </div>
      <div aria-live="polite" className="min-h-5 text-sm">
        {reply.isError && <p className="text-fail">{supportErrorMessage(reply.error)}</p>}
      </div>
    </form>
  );
}

function Inner({ initialCatalogue }: { initialCatalogue?: SupportCatalogue }) {
  const catalogue = useCatalogue(initialCatalogue);
  const [conversation, setConversation] = useState<Conversation | null>(null);

  if (catalogue.isPending) return <p className="text-sm text-muted">Loading scenarios…</p>;
  if (catalogue.isError) {
    return <p className="text-sm text-fail">{supportErrorMessage(catalogue.error)}</p>;
  }

  return (
    <div className="space-y-6">
      {conversation === null ? (
        <Starter catalogue={catalogue.data} onStarted={setConversation} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <section aria-label="Conversation" className="min-w-0 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted">
                Customer {conversation.customer_id}{" "}
                {conversation.status === "awaiting_approval" && (
                  <Pill tone="warn">Waiting for your approval</Pill>
                )}
              </p>
              <button
                type="button"
                className={buttonClasses("quiet")}
                onClick={() => setConversation(null)}
              >
                Start another
              </button>
            </div>
            <Chat conversation={conversation} />
            <ApprovalCard conversation={conversation} onDecided={setConversation} />
            <Records conversation={conversation} />
            <FollowUp conversation={conversation} onReplied={setConversation} />
          </section>
          <section
            aria-label="Agent trace"
            className="min-w-0 rounded-md bg-surface p-4 ring-1 ring-inset ring-line"
          >
            <h3 className="text-sm font-semibold text-text">What the agent did</h3>
            <div className="mt-3">
              <Trace conversation={conversation} />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

/** The interactive demo; mounts its own query cache like the other demo islands. */
export function AgentDemo({ initialCatalogue }: { initialCatalogue?: SupportCatalogue }) {
  return (
    <QueryProvider>
      <Inner initialCatalogue={initialCatalogue} />
    </QueryProvider>
  );
}
