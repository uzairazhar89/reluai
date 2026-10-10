import { Fragment } from "react";

import type { Conversation, TranscriptEntry } from "@/lib/api/types";

const roleLabel: Record<TranscriptEntry["role"], string> = {
  customer: "Customer",
  agent: "Agent (draft, not sent)",
  supervisor: "Supervisor (you)",
};

/** Agent text with [n] turned into links to the cited policy passage. */
function WithCitations({ text, max }: { text: string; max: number }) {
  const parts = text.split(/(\[\d{1,2}\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d{1,2})\]$/);
        const n = m ? Number(m[1]) : 0;
        if (m && n >= 1 && n <= max) {
          return (
            <a
              key={i}
              href={`#policy-source-${n}`}
              className="prose-link mx-0.5 align-super text-[0.7rem]"
              aria-label={`Policy passage ${n}`}
            >
              {n}
            </a>
          );
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

export function Chat({ conversation }: { conversation: Conversation }) {
  const max = conversation.sources.length;
  return (
    <div className="space-y-3">
      <ol className="space-y-3" aria-label="Conversation">
        {conversation.transcript.map((t, i) => (
          <li
            key={i}
            className={`max-w-[92%] rounded-md px-3.5 py-2.5 text-[0.95rem] leading-relaxed ${
              t.role === "customer"
                ? "bg-surface-2 text-text"
                : t.role === "supervisor"
                  ? "ml-auto ring-1 ring-inset ring-warn/40"
                  : "ml-auto bg-ink text-text ring-1 ring-inset ring-line-strong"
            }`}
          >
            <p className="mb-1 text-xs text-faint">{roleLabel[t.role]}</p>
            <p className="whitespace-pre-line">
              {t.role === "agent" ? <WithCitations text={t.text} max={max} /> : t.text}
            </p>
          </li>
        ))}
      </ol>
      {max > 0 && (
        <div className="border-t border-line pt-3">
          <p className="text-xs text-faint">
            Policy passages the agent retrieved (the policy was written for this demo)
          </p>
          <ol className="mt-2 space-y-2 text-sm">
            {conversation.sources.map((s) => (
              <li key={s.number} id={`policy-source-${s.number}`} className="scroll-mt-28">
                <span className="num mr-2 text-faint">[{s.number}]</span>
                <span className="font-medium text-text">{s.heading}</span>
                <span className="block pl-7 text-muted">{s.quote}…</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
