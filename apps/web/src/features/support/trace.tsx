import type { Conversation, ConversationStep } from "@/lib/api/types";
import { formatInt } from "@/lib/format";

type Json = Record<string, unknown>;

const money = (x: unknown) =>
  typeof x === "number" ? `£${x.toLocaleString("en-GB", { minimumFractionDigits: 2 })}` : "–";

/** One line saying what a tool returned. */
export function toolSummary(step: ConversationStep): string {
  const r = (step.result ?? {}) as Json;
  if (!step.ok) return String(r.error ?? "error");
  switch (step.name) {
    case "get_invoice": {
      const products = (r.products as unknown[] | undefined)?.length ?? 0;
      return `${products} products, total ${money(r.total_gbp)}${r.is_credit_note ? " (credit note)" : ""}`;
    }
    case "list_customer_invoices":
      return `${(r.invoices as unknown[] | undefined)?.length ?? 0} recent invoices`;
    case "get_shipment_status":
      return r.shipment === null
        ? "no shipment (credit note)"
        : `${String(r.status).replaceAll("_", " ")}${r.delivered_on ? ` on ${String(r.delivered_on)}` : `, due ${String(r.estimated_delivery)}`} (simulated)`;
    case "search_policy": {
      const passages = (r.passages as { citation: number; section: string }[] | undefined) ?? [];
      return passages.map((p) => `[${p.citation}] ${p.section}`).join("; ") || "no passage found";
    }
    case "calculate_refund":
      return r.eligible
        ? `eligible: ${money(r.amount_gbp)}${r.refund_on_return ? " when the items are returned" : `, ${String(r.approval_needed)}`}`
        : "not eligible";
    case "request_approval":
      return r.status === "approved"
        ? "approved by the agent (within limit)"
        : String(r.status ?? "").replaceAll("_", " ");
    case "create_ticket":
      return `${String(r.ticket_id ?? "")} ${String(r.category ?? "").replaceAll("_", " ")}`.trim();
    case "draft_reply":
      return "reply drafted (not sent)";
    default:
      return "done";
  }
}

const outcomeWords: Record<string, string> = {
  not_configured: "not configured",
  rate_limited: "rate limited",
  unavailable: "unavailable",
  budget_exhausted: "daily budget used",
};

/** "fell back after groq: not_configured" → "Skipped groq (not configured)." */
export function fallbackSentence(note: string): string {
  const skipped = note
    .replace(/^fell back after /, "")
    .split(", ")
    .map((part) => {
      const [name, outcome] = part.split(": ");
      return `${name} (${outcomeWords[outcome ?? ""] ?? outcome})`;
    });
  return `Skipped ${skipped.join(", ")}, so the next provider answered.`;
}

function argText(args: ConversationStep["arguments"]): string {
  if (!args) return "";
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
}

function providerLabel(step: ConversationStep): string {
  if (step.provider === "scripted") return "Scripted agent";
  if (!step.provider) return step.name;
  return `${step.provider} ${step.model ?? ""}`.trim();
}

interface Group {
  model: ConversationStep;
  calls: ConversationStep[];
  firstOfTurn: boolean;
}

function groups(steps: ConversationStep[]): (Group | ConversationStep)[] {
  const out: (Group | ConversationStep)[] = [];
  let current: Group | null = null;
  let turn = 0;
  for (const s of steps) {
    if (s.kind === "model") {
      current = { model: s, calls: [], firstOfTurn: s.turn !== turn };
      turn = s.turn;
      out.push(current);
    } else if (s.kind === "tool" && current) {
      current.calls.push(s);
    } else {
      current = null;
      out.push(s);
    }
  }
  return out;
}

function ToolRow({ step }: { step: ConversationStep }) {
  const body = JSON.stringify(step.result, null, 2) ?? "";
  return (
    <li className="min-w-0">
      <details className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2 rounded-sm px-1 py-0.5 hover:bg-surface-2">
          <span
            aria-hidden
            className={`size-1.5 shrink-0 translate-y-[-1px] rounded-full ${step.ok ? "bg-pass" : "bg-fail"}`}
          />
          <span className="font-mono text-[0.8125rem] text-text">{step.name}</span>
          <span className="block basis-full truncate pl-3.5 font-mono text-xs text-faint">
            {argText(step.arguments)}
          </span>
          <span className={`basis-full pl-3.5 text-xs ${step.ok ? "text-muted" : "text-fail"}`}>
            <span className="sr-only">{step.ok ? "Result: " : "Error: "}</span>
            {toolSummary(step)}
            {step.note ? `; ${step.note}` : ""}
          </span>
        </summary>
        <pre className="ml-3.5 mt-1 max-h-64 overflow-auto rounded-sm bg-ink p-3 font-mono text-xs leading-relaxed text-muted ring-1 ring-line">
          {body.length > 4000 ? `${body.slice(0, 4000)}\n…` : body}
        </pre>
      </details>
    </li>
  );
}

export function Trace({ conversation }: { conversation: Conversation }) {
  const items = groups(conversation.steps);
  const modelSteps = conversation.steps.filter((s) => s.kind === "model");
  const fellBack = modelSteps.find((s) => s.note?.startsWith("fell back"));
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted">
        {formatInt(modelSteps.length)} agent steps,{" "}
        {formatInt(conversation.steps.filter((s) => s.kind === "tool").length)} tool calls,{" "}
        {formatInt(conversation.tokens)} model tokens.
        {fellBack ? ` ${fallbackSentence(fellBack.note ?? "")}` : ""}
      </p>
      <ol className="space-y-2">
        {items.map((item) => {
          if ("calls" in item) {
            return (
              <li key={item.model.seq}>
                {item.firstOfTurn && (
                  <p className="mb-1.5 mt-3 border-t border-line pt-2 text-xs text-faint first:mt-0">
                    Turn {item.model.turn}
                  </p>
                )}
                <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
                  <span className="num text-faint">{item.model.seq}</span>
                  <span className="font-medium text-text">{providerLabel(item.model)}</span>
                  <span className="text-faint">
                    {item.model.prompt_tokens + item.model.completion_tokens > 0
                      ? `${formatInt(item.model.prompt_tokens + item.model.completion_tokens)} tokens, `
                      : ""}
                    {item.model.latency_ms} ms
                    {item.calls.length > 1 ? `, ${item.calls.length} calls at once` : ""}
                  </span>
                </p>
                {item.calls.length > 0 && (
                  <ul className="mt-1 space-y-1 border-l border-line pl-2">
                    {item.calls.map((c: ConversationStep) => (
                      <ToolRow key={c.seq} step={c} />
                    ))}
                  </ul>
                )}
              </li>
            );
          }
          return (
            <li
              key={item.seq}
              className="rounded-sm px-2 py-1.5 text-xs ring-1 ring-inset ring-warn/40"
            >
              <span className="font-medium text-warn">Supervisor</span>{" "}
              <span className="text-text">
                {String((item.arguments as Json | null)?.decision ?? "")}{" "}
                {money((item.result as Json | null)?.amount)}
              </span>
              {item.note ? <span className="text-muted">: {item.note}</span> : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
