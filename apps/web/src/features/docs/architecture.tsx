/**
 * Document Q&A as an HTML flow: an uploaded PDF is read in an isolated process (text layer or
 * OCR), rebuilt into headings and passages, indexed for keyword and meaning-based search, and
 * questions are answered from the retrieved passages with page citations.
 */
const ingest = [
  ["Isolated reader", "Own process with memory, CPU-time and wall-clock caps and no secrets"],
  ["Text layer", "PDFium: each line with its position, font size and weight"],
  ["OCR for scans", "PP-OCRv6 small on CPU (ONNX Runtime), up to 5 pages per document"],
  ["Layout", "Headers and footers removed; headings and paragraphs rebuilt; page map kept"],
  ["Passages", "~150-word spans under their heading path, one sentence of overlap"],
  ["Index", "PostgreSQL full-text (headings weighted) and bge-small embeddings in pgvector"],
];

const answer = [
  ["Hybrid retrieval", "Keyword and vector rankings merged by reciprocal-rank fusion"],
  ["Extractive", "Best sentences quoted with citations; abstains when nothing matches"],
  ["Model (optional)", "Groq or the local model writes from the passages; citations checked"],
];

export function DocsArchitecture() {
  return (
    <figure className="rounded-md border border-line bg-surface p-5 text-sm">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-medium text-faint">When a PDF is uploaded (worker)</p>
          <ol className="space-y-1.5">
            {ingest.map(([name, note], i) => (
              <li key={name} className="flex gap-3 rounded-sm bg-surface-2 px-3 py-2">
                <span className="num w-4 shrink-0 text-xs text-faint">{i + 1}</span>
                <span>
                  <span className="block font-medium text-text">{name}</span>
                  <span className="block text-xs text-muted">{note}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
        <div>
          <p className="mb-2 text-xs font-medium text-faint">When a question is asked (API)</p>
          <ol className="space-y-1.5">
            {answer.map(([name, note], i) => (
              <li
                key={name}
                className={`flex gap-3 rounded-sm px-3 py-2 ${i === 0 ? "ring-1 ring-inset ring-link/50" : "ring-1 ring-inset ring-line-strong"}`}
              >
                <span className="num w-4 shrink-0 text-xs text-faint">{i + 1}</span>
                <span>
                  <span className="block font-medium text-text">{name}</span>
                  <span className="block text-xs text-muted">{note}</span>
                </span>
              </li>
            ))}
          </ol>
          <p className="mt-4 text-xs text-muted">
            <span className="font-medium text-text">Privacy.</span> The PDF waits in memory (a tmpfs
            shared by the API and worker) until it is read, then is discarded. Its text and passages
            are deleted after an hour, or at once with “Delete now”. Passages go to a hosted model
            only if the visitor ticks the box.
          </p>
        </div>
      </div>
      <figcaption className="sr-only">
        An uploaded PDF is read in an isolated process, using the text layer or OCR, rebuilt into
        headings and passages and indexed in PostgreSQL for keyword and vector search. A question
        retrieves passages by both, and the answer quotes or summarises them with page citations.
      </figcaption>
    </figure>
  );
}
