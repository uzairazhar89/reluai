import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink } from "@/components/button-link";
import { JsonLd } from "@/components/json-ld";
import { ProjectSection, ProjectToc } from "@/components/project-page";
import { Pill } from "@/components/status-badge";
import { projects } from "@/content/projects";
import { DocsArchitecture } from "@/features/docs/architecture";
import { QaDemo } from "@/features/docs/qa-demo";
import { serverGet } from "@/lib/api/server";
import type { DocumentInfo, DocumentQaItem, DocumentQaRun } from "@/lib/api/types";
import { formatDateTime, formatInt } from "@/lib/format";
import { site } from "@/lib/site";

export const revalidate = 60;

const project = projects.find((p) => p.slug === "document-intelligence")!;
const repoTree = `${site.repo}/tree/main/${project.repoPath}`;
const repoFile = (path: string) =>
  `${site.repo}/blob/main/${project.repoPath}/src/reluai_docs/${path}`;

export const metadata: Metadata = {
  title: project.title,
  description:
    "Upload a PDF and ask questions about it. The document is read in an isolated process " +
    "(text layer or OCR), searched by keywords and meaning, and every answer cites the pages " +
    "it came from, or says the document does not cover the question.",
  alternates: { canonical: `/projects/${project.slug}` },
};

const stack = [
  ["Reading", "PDFium (pypdfium2) for the text layer; PP-OCRv6 small via RapidOCR for scans"],
  ["Isolation", "A separate process per PDF with address-space, CPU-time and write limits"],
  ["Structure", "Headings, paragraphs and page numbers rebuilt from line geometry"],
  ["Search", "PostgreSQL full-text search and bge-small-en-v1.5 embeddings in pgvector"],
  ["Answers", "Extractive by default; Groq or the local model when allowed, citations checked"],
  ["Interface", "FastAPI and a Procrastinate job; Next.js with live progress and citations"],
] as const;

const failures = [
  [
    "A malformed or hostile PDF",
    "It is parsed in its own process with no secrets in its environment, capped at 1.5 GB of address space, 90 seconds of CPU and 60 seconds of wall time, and forbidden to write files. If it hangs or crashes, the visitor sees a plain message and nothing else is affected.",
  ],
  [
    "A scanned PDF with no text layer",
    "Pages with images but no text are read with OCR on the server's CPU, up to 5 pages per document because each takes one to two seconds. Pages beyond the limit are listed as not read rather than silently missing.",
  ],
  [
    "Password-protected, damaged or non-PDF files",
    "Rejected with a specific reason: the file signature is checked on upload, and the reader reports encryption or damage separately.",
  ],
  [
    "The document does not contain the answer",
    "The extractive answerer abstains when no sentence covers enough of the question (by words or by meaning); a model can only answer through a tool that requires citations, or call not_in_document.",
  ],
  [
    "A model cites a passage it was not given",
    "Citations are checked against the passages actually sent. The model gets one retry with the problem explained; after that the answer falls back to extractive, and the trace says so.",
  ],
  [
    "Text inside the PDF tries to instruct the model",
    "Passages are marked as data in the prompt, the model can only call two narrow tools, and its answer is displayed as plain text. It has no other tools to misuse.",
  ],
  [
    "Many uploads at once",
    "Five uploads per visitor per hour, at most six documents in progress, and reading shares the server's single CPU lease with other heavy jobs, so pages stay responsive.",
  ],
] as const;

function pct(n: number | undefined) {
  return n === undefined ? "–" : `${n.toFixed(1)}%`;
}

const runName = (label: string) => (label === "extractive" ? "Extractive (no model)" : label);

function missReason(item: DocumentQaItem) {
  if (item.kind === "unanswerable") return "Answered, but the document does not cover it";
  if (item.abstained) return "Abstained, but the document answers it";
  if (!item.retrieved) return "The page with the answer was not retrieved";
  return "Quoted passages without the required facts";
}

function Misses({ run }: { run: DocumentQaRun }) {
  const missed = run.results.filter((r) => !r.correct);
  if (missed.length === 0) return null;
  return (
    <details className="group">
      <summary className="cursor-pointer rounded-sm py-1 text-text hover:underline">
        {runName(run.label)}: the {missed.length} question{missed.length === 1 ? "" : "s"} it got
        wrong
      </summary>
      <ul className="mt-2 space-y-2.5 text-sm">
        {missed.map((m) => (
          <li key={m.id} className="border-l-2 border-line pl-3">
            <span className="text-text">{m.question}</span>
            <span className="block text-muted">
              {missReason(m)}. {m.split === "held_out" ? "Held-out" : "Development"} half.
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function ResultsBody({ runs }: { runs: DocumentQaRun[] }) {
  return (
    <>
      <p>
        A fixed set of questions about the sample document, written with the page each answer is on
        and the facts a correct answer must contain, plus questions the document does not answer
        (the right response is to abstain). Checks are mechanical, so no model judges another.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">Question answering results per method</caption>
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th scope="col" className="py-2 pr-3 text-left font-medium">
                Method
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Correct
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Held-out set
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Right page retrieved
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Median time
              </th>
              <th scope="col" className="py-2 text-left font-medium">
                Run
              </th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.label} className="border-b border-line/60">
                <th scope="row" className="py-2 pr-3 text-left font-medium text-text">
                  {runName(r.label)}
                </th>
                <td className="num py-2 pr-3 text-right text-text">
                  {r.correct} of {r.questions}
                </td>
                <td className="num py-2 pr-3 text-right">{pct(r.metrics.held_out_accuracy)}</td>
                <td className="num py-2 pr-3 text-right">{pct(r.metrics.retrieval_recall)}</td>
                <td className="num py-2 pr-3 text-right">{formatInt(r.median_latency_ms)} ms</td>
                <td className="py-2 text-muted">{formatDateTime(r.ran_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        The abstention thresholds were tuned on the development half of the questions only; the
        held-out half is reported separately so the tuning cannot flatter the result. The halves
        differ in one way that shows in the scores: the development half&apos;s unanswerable
        questions are off-topic (a recipe, a football result), while four of the five held-out ones
        are close to the document&apos;s subject (an error-rate threshold, NIST&apos;s headcount).
        Those are where quoting the nearest sentence goes wrong, and where a model with a &ldquo;not
        in the document&rdquo; tool should do better. A model is scored only when a free-tier key is
        configured, with no extractive fallback, so a model failure counts as a failure.
      </p>
      <div className="space-y-2">
        {runs.map((r) => (
          <Misses key={r.label} run={r} />
        ))}
      </div>
    </>
  );
}

export default async function DocumentQaPage() {
  const [sample, evaluation] = await Promise.all([
    serverGet<DocumentInfo>("/api/documents/sample", revalidate),
    serverGet<DocumentQaRun[]>("/api/documents/evaluation", revalidate),
  ]);

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "SoftwareSourceCode",
          name: project.title,
          description: metadata.description,
          codeRepository: repoTree,
          programmingLanguage: ["Python", "TypeScript"],
          author: { "@type": "Person", name: site.name, url: site.url },
          license: "https://opensource.org/licenses/MIT",
        }}
      />

      <header className="mx-auto max-w-6xl px-5 pb-12 pt-12 sm:px-8 md:pt-16">
        <nav aria-label="Breadcrumb" className="text-sm text-muted">
          <Link href="/projects" className="hover:text-text">
            Projects
          </Link>
          <span aria-hidden className="mx-2 text-faint">
            /
          </span>
          <span aria-current="page">{project.title}</span>
        </nav>
        <h1 className="display mt-5 max-w-[22ch] text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">
          {project.title}
        </h1>
        <p className="mt-5 max-w-[62ch] text-lg text-muted">
          Upload a PDF, including a scanned one, and ask questions about it. Every answer quotes or
          cites the pages it came from, and when the document does not cover a question, it says so
          instead of guessing.
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Pill tone="pass">Live</Pill>
          <Pill>AI and LLM apps</Pill>
          <Pill>Works without a model</Pill>
          <Pill>Your PDF or a real NIST publication</Pill>
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <ButtonLink href="#demo">Try the live demo</ButtonLink>
          <ButtonLink href={repoTree} variant="secondary" external>
            Source code
          </ButtonLink>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-12 px-5 pb-24 sm:px-8 lg:grid-cols-[12rem_minmax(0,1fr)]">
        <ProjectToc />
        <div className="min-w-0 space-y-14">
          <ProjectSection id="problem">
            <p>
              Contracts, policies, standards and reports run to dozens of pages, and the answer to a
              question is usually one paragraph somewhere in the middle. Search finds words, not
              answers; chat tools over PDFs answer fluently but rarely say where, and fill gaps with
              things the document never said.
            </p>
            <p>
              Real PDFs make it harder: running headers on every page, two-column layouts, words
              broken across lines, and scans with no text at all.
            </p>
          </ProjectSection>

          <ProjectSection id="why">
            <p>
              An answer from a document is only worth acting on if it can be checked in seconds.
              That needs the exact passage and page, a clear &ldquo;not in this document&rdquo; when
              it is not there, and a pipeline that copes with the PDFs people actually have. Those
              are the parts this project shows, with everything visible: how the file was read, how
              it was split, why each passage was retrieved.
            </p>
          </ProjectSection>

          <ProjectSection id="solution">
            <p>
              The PDF is read in an isolated process: the text layer where there is one, OCR where a
              page is a scan. Headings, paragraphs and page numbers are rebuilt from the geometry of
              each line, and the text is split into passages that remember their heading and page.
              Each passage is indexed twice, for keyword search and for meaning-based search.
            </p>
            <p>
              A question retrieves passages by both and merges the rankings. Without any language
              model, the answer quotes the best-matching sentences with their citations, or
              abstains. When a model is allowed, it writes the answer from the same passages and
              must cite them; invented citations are caught.
            </p>
          </ProjectSection>

          <ProjectSection id="architecture">
            <DocsArchitecture />
          </ProjectSection>

          <ProjectSection id="implementation">
            <dl className="divide-y divide-line/60">
              {stack.map(([term, desc]) => (
                <div key={term} className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr] sm:gap-6">
                  <dt className="font-medium text-text">{term}</dt>
                  <dd>{desc}</dd>
                </div>
              ))}
            </dl>
            <p>
              <strong>Rebuilding structure.</strong> For every line the reader records its box, font
              size and weight. Lines repeated in the top or bottom margin of many pages are running
              headers or footers and are dropped. Lines set clearly larger than the body text, or
              short bold or capitalised lines standing alone, become headings, nested by size and
              then by section number; if more than a third of the lines look like headings (slides,
              forms), the weaker signals are ignored. Paragraph breaks come from extra spacing,
              bullets, indented first lines and short closing lines. Words split by a hyphen at a
              line end are rejoined unless the document itself writes them with one
              (&ldquo;context-specific&rdquo;), and a paragraph that runs onto the next page stays
              whole.
            </p>
            <p>
              <strong>Passages and pages.</strong> The shared retrieval package splits the text into
              passages of about 150 words that are exact spans of the text, each filed under its
              heading path. A page map records where each page starts, so any passage resolves to
              the page or pages it came from.
            </p>
            <p>
              <strong>Hybrid search.</strong> PostgreSQL full-text search ranks passages with
              headings weighted above body text, and falls back to matching any word when all words
              find nothing. Passages and questions are embedded with BAAI bge-small-en-v1.5 (384
              dimensions) in ONNX Runtime on CPU, with a pure-Python WordPiece tokenizer; the two
              rankings are merged by reciprocal-rank fusion. Questions that ask what something is
              also rank passages that define it.
            </p>
            <p>
              <strong>A smaller model.</strong> The embedding model runs as an 8-bit quantised copy,
              made at build time. In development runs on two CPU cores it embedded passages 2.4
              times faster, took under half the memory once loaded, and answered 32 of the 40
              questions against 33 for the full-precision model; the one difference is an
              unanswerable question the full model abstained on.
            </p>
          </ProjectSection>

          <ProjectSection id="demo">
            <p>
              Start with the sample, the NIST AI Risk Management Framework, or upload your own PDF.
              Click a citation to see the passage it points to.
            </p>
            <div className="pt-2 text-base">
              <QaDemo initialSample={sample.ok ? sample.data : undefined} />
            </div>
            <p className="text-sm text-faint">
              Portfolio demonstration. Each visitor can upload 5 PDFs and ask 30 questions an hour.
              Uploaded text is deleted after an hour. Answers are generated from the document and
              may be incomplete; check the cited passages.
            </p>
          </ProjectSection>

          <ProjectSection id="results">
            {evaluation.ok && evaluation.data.length > 0 ? (
              <ResultsBody runs={evaluation.data} />
            ) : (
              <p>
                Results are read from the running system and are not available right now. They
                appear after the first scheduled run of the question set.
              </p>
            )}
          </ProjectSection>

          <ProjectSection id="failure-handling">
            <dl className="divide-y divide-line/60">
              {failures.map(([term, desc]) => (
                <div key={term} className="py-3.5">
                  <dt className="font-medium text-text">{term}</dt>
                  <dd className="mt-1">{desc}</dd>
                </div>
              ))}
            </dl>
          </ProjectSection>

          <ProjectSection id="deployment">
            <p>
              Uploads are accepted by the API and read by the worker, which takes the server&apos;s
              CPU lease for the duration. The file passes between them through an in-memory volume
              and is deleted as soon as it is read. The embedding model and the sample document are
              downloaded when the image is built, from pinned sources checked against their SHA-256
              hashes, and the sample is indexed and embedded at build time.
            </p>
            <p>
              A job every ten minutes deletes expired uploads with their passages, and a daily job
              re-runs the question set so the results above come from this server.
            </p>
          </ProjectSection>

          <ProjectSection id="cost">
            <p>
              <strong>$0 in API spend.</strong> Reading, OCR, embeddings and extractive answers all
              run on the server&apos;s CPU. A hosted model is used only when a free-tier key is
              configured and, for uploads, only when the visitor allows it; a question then sends
              the instructions and up to six passages, a few thousand characters, through the same
              token ledger and daily limits as the other projects.
            </p>
          </ProjectSection>

          <ProjectSection id="limitations">
            <ul className="list-disc space-y-1.5 pl-5">
              <li>
                Structure is inferred from layout. Unusual layouts (multi-column scans, text in
                images inside text pages, complex tables) can come out in the wrong order or with
                headings missed. Tables are read as lines of text.
              </li>
              <li>
                OCR is limited to 5 pages per document and to printed text; handwriting is not
                recognised.
              </li>
              <li>
                Extractive answers quote; they do not combine facts from different passages.
                Questions that need reasoning across the document are better answered by the model,
                when one is configured.
              </li>
              <li>
                The question set covers one document. Accuracy on other documents will differ, which
                is why every answer shows its passages.
              </li>
              <li>English only: the embedding model and stemming are English.</li>
            </ul>
          </ProjectSection>

          <ProjectSection id="source">
            <p>
              The full source is on GitHub under the MIT licence, with the tests and question set.
            </p>
            <ul className="space-y-2">
              {(
                [
                  ["pdfread.py", "Text layer and OCR, line by line"],
                  ["isolation.py", "The resource-capped reader process"],
                  ["layout.py", "Headings, paragraphs and the page map"],
                  ["embedding.py", "ONNX embeddings and the model pins"],
                  ["answer.py", "Extractive answers, the model path and citation checks"],
                  ["service.py", "Upload, processing, questions and expiry"],
                  ["questions.py", "The evaluation question set"],
                ] as const
              ).map(([file, what]) => (
                <li key={file} className="flex flex-wrap gap-x-3">
                  <a href={repoFile(file)} className="prose-link font-mono text-sm">
                    {file}
                  </a>
                  <span>{what}</span>
                </li>
              ))}
            </ul>
            <div className="pt-2">
              <ButtonLink href={repoTree} variant="secondary" external>
                View on GitHub
              </ButtonLink>
            </div>
            <p className="text-sm text-faint">
              Sample: National Institute of Standards and Technology (2023), Artificial Intelligence
              Risk Management Framework (AI RMF 1.0), NIST AI 100-1, a work of the US Government.
              Embedding model: BAAI bge-small-en-v1.5, MIT licence. OCR models: PaddleOCR PP-OCRv6
              via RapidOCR, Apache 2.0. Details on the{" "}
              <Link href="/data" className="prose-link">
                data page
              </Link>
              .
            </p>
          </ProjectSection>
        </div>
      </div>
    </>
  );
}
