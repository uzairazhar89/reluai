import { describe, expect, it } from "vitest";

import {
  answerParts,
  fileSize,
  matchLabel,
  pagesLabel,
  segments,
  stageLabel,
  whyRetrieved,
} from "./format";

describe("docs format", () => {
  it("labels pages", () => {
    expect(pagesLabel(3, 3)).toBe("p. 3");
    expect(pagesLabel(3, 4)).toBe("pp. 3–4");
  });

  it("describes processing stages", () => {
    expect(stageLabel({ status: "reading", progress_done: 0, progress_total: 40 })).toBe(
      "Reading page 1 of 40",
    );
    expect(stageLabel({ status: "ocr", progress_done: 1, progress_total: 3 })).toBe(
      "Reading scanned page 2 of 3 with OCR",
    );
    expect(stageLabel({ status: "embedding", progress_done: 64, progress_total: 1200 })).toBe(
      "Embedding passages: 64 of 1,200",
    );
    expect(stageLabel({ status: "queued", progress_done: 0, progress_total: 0 })).toBe(
      "Waiting for the reader",
    );
  });

  it("splits text into marked segments", () => {
    expect(
      segments("abcdefghij", [
        [6, 8],
        [1, 3],
        [2, 4],
      ]),
    ).toEqual([
      { text: "a", mark: false },
      { text: "bcd", mark: true },
      { text: "ef", mark: false },
      { text: "gh", mark: true },
      { text: "ij", mark: false },
    ]);
    expect(segments("abc", [[5, 9]])).toEqual([{ text: "abc", mark: false }]);
  });

  it("finds citations in an answer", () => {
    expect(answerParts("Ten days [1]. Also [2, 3]")).toEqual([
      { kind: "text", text: "Ten days " },
      { kind: "cite", numbers: [1] },
      { kind: "text", text: ". Also " },
      { kind: "cite", numbers: [2, 3] },
    ]);
    expect(answerParts("No citations")).toEqual([{ kind: "text", text: "No citations" }]);
  });

  it("explains retrieval and sizes", () => {
    expect(whyRetrieved({ keyword_rank: 2, vector_rank: 1, similarity: 0.8123 })).toBe(
      "keyword match #2, meaning match #1, similarity 0.81",
    );
    expect(whyRetrieved({ keyword_rank: null, vector_rank: null, similarity: null })).toBe(
      "retrieved",
    );
    expect(fileSize(1_946_127)).toBe("1.9 MB");
    expect(fileSize(5300)).toBe("5 KB");
  });

  it("states what the answer-or-abstain decision was based on", () => {
    expect(matchLabel({ method: "extractive", word_overlap: 0.7332, similarity: 0.6807 })).toBe(
      "Best sentence: 73% of the question's words, similarity 0.68",
    );
    expect(matchLabel({ method: "extractive", word_overlap: 0.25, similarity: null })).toBe(
      "Best sentence: 25% of the question's words",
    );
    expect(matchLabel({ method: "model", word_overlap: null, similarity: null })).toBeNull();
  });
});
