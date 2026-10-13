import type { DocumentAnswer, DocumentInfo } from "@/lib/api/types";
import { formatInt } from "@/lib/format";

/** "p. 3" or "pp. 3–4". */
export function pagesLabel(from: number, to: number): string {
  return from === to ? `p. ${from}` : `pp. ${from}–${to}`;
}

/** What the reader is doing right now, for the progress line. */
export function stageLabel(doc: Pick<DocumentInfo, "status" | "progress_done" | "progress_total">) {
  const { status, progress_done: done, progress_total: total } = doc;
  switch (status) {
    case "queued":
      return "Waiting for the reader";
    case "reading":
      return total ? `Reading page ${Math.min(done + 1, total)} of ${total}` : "Reading the PDF";
    case "ocr":
      return total
        ? `Reading scanned page ${Math.min(done + 1, total)} of ${total} with OCR`
        : "Reading scanned pages with OCR";
    case "indexing":
      return "Splitting into passages and indexing";
    case "embedding":
      return total
        ? `Embedding passages: ${formatInt(Math.min(done, total))} of ${formatInt(total)}`
        : "Embedding passages";
    case "ready":
      return "Ready";
    case "failed":
      return "Could not be read";
  }
}

/** 0–1 share of the current stage that is done, or null when unknown. */
export function stageProgress(
  doc: Pick<DocumentInfo, "status" | "progress_done" | "progress_total">,
): number | null {
  if (doc.status === "ready") return 1;
  if (!doc.progress_total) return null;
  return Math.min(1, doc.progress_done / doc.progress_total);
}

export const isProcessing = (status: DocumentInfo["status"]) =>
  status !== "ready" && status !== "failed";

export interface Segment {
  text: string;
  mark: boolean;
}

/** Split ``text`` into plain and marked runs; ranges may be unsorted or overlap. */
export function segments(text: string, ranges: [number, number][]): Segment[] {
  const sorted = ranges
    .map(([s, e]) => [Math.max(0, s), Math.min(text.length, e)] as const)
    .filter(([s, e]) => e > s)
    .sort((a, b) => a[0] - b[0]);
  const out: Segment[] = [];
  let pos = 0;
  for (const [s, e] of sorted) {
    const start = Math.max(s, pos);
    if (start > pos) out.push({ text: text.slice(pos, start), mark: false });
    if (e > start) {
      const prev = out[out.length - 1];
      if (prev?.mark && start === pos) prev.text += text.slice(start, e);
      else out.push({ text: text.slice(start, e), mark: true });
    }
    pos = Math.max(pos, e);
  }
  if (pos < text.length) out.push({ text: text.slice(pos), mark: false });
  return out;
}

export type AnswerPart = { kind: "text"; text: string } | { kind: "cite"; numbers: number[] };

/** Split an answer into text and citation markers ("[2]", "[1, 3]"). */
export function answerParts(answer: string): AnswerPart[] {
  const parts: AnswerPart[] = [];
  const re = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g;
  let last = 0;
  for (const m of answer.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: answer.slice(last, at) });
    parts.push({ kind: "cite", numbers: m[1]!.split(",").map((n) => Number(n.trim())) });
    last = at + m[0].length;
  }
  if (last < answer.length) parts.push({ kind: "text", text: answer.slice(last) });
  return parts;
}

/** Who wrote the answer, for its badge. */
export function methodLabel(a: Pick<DocumentAnswer, "method" | "provider" | "model">): string {
  if (a.method === "extractive") return "Extractive (no model)";
  return [a.provider, a.model].filter(Boolean).join(" ") || "Model";
}

/**
 * How well the best sentence matched the question, for extractive answers: the measures the
 * answer-or-abstain decision is made on.
 */
export function matchLabel(
  a: Pick<DocumentAnswer, "method" | "word_overlap" | "similarity">,
): string | null {
  if (a.method !== "extractive" || a.word_overlap === null || a.word_overlap === undefined) {
    return null;
  }
  const words = `${Math.round(a.word_overlap * 100)}% of the question's words`;
  return a.similarity === null || a.similarity === undefined
    ? `Best sentence: ${words}`
    : `Best sentence: ${words}, similarity ${a.similarity.toFixed(2)}`;
}

/** Why a passage was retrieved: its rank in the keyword and meaning-based lists. */
export function whyRetrieved(p: {
  keyword_rank: number | null;
  vector_rank: number | null;
  similarity: number | null;
}): string {
  const parts: string[] = [];
  if (p.keyword_rank) parts.push(`keyword match #${p.keyword_rank}`);
  if (p.vector_rank) parts.push(`meaning match #${p.vector_rank}`);
  if (p.similarity !== null && p.similarity !== undefined)
    parts.push(`similarity ${p.similarity.toFixed(2)}`);
  return parts.join(", ") || "retrieved";
}

export function fileSize(bytes: number): string {
  if (bytes < 1000) return `${bytes} bytes`;
  if (bytes < 1_000_000) return `${formatInt(Math.round(bytes / 1000))} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}
