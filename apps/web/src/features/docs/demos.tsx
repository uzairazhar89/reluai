"use client";

import { useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";

import type { DocumentInfo } from "@/lib/api/types";

import { InvoiceDemo } from "./invoice-demo";
import { QaDemo } from "./qa-demo";

const TABS = [
  ["ask", "Ask a document"],
  ["invoice", "Read an invoice"],
] as const;
type Tab = (typeof TABS)[number][0];

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** The two demos as tabs; "#invoice" in the address opens (and scrolls to) the invoice one. */
export function DocsDemos({ initialSample }: { initialSample?: DocumentInfo }) {
  const hash = useSyncExternalStore(
    subscribe,
    () => window.location.hash,
    () => "",
  );
  const [chosen, setTab] = useState<Tab | null>(null);
  const tab: Tab = chosen ?? (hash === "#invoice" ? "invoice" : "ask");
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKey = (e: KeyboardEvent, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    setTab(TABS[next]?.[0] ?? "ask");
    refs.current[next]?.focus();
  };

  return (
    <div id="invoice" className="scroll-mt-24 space-y-6">
      <div role="tablist" aria-label="Demos" className="flex gap-1 border-b border-line">
        {TABS.map(([id, label], i) => (
          <button
            key={id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={`tab-${id}`}
            role="tab"
            type="button"
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            onKeyDown={(e) => onKey(e, i)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
              tab === id
                ? "border-text font-medium text-text"
                : "border-transparent text-muted hover:text-text"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        tabIndex={0}
        className="focus-visible:outline-none"
      >
        {tab === "ask" ? <QaDemo initialSample={initialSample} /> : <InvoiceDemo />}
      </div>
    </div>
  );
}
