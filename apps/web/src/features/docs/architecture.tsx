/**
 * Document Intelligence as an HTML flow: every PDF is read by the same isolated reader (text
 * layer or OCR); a document for questions is rebuilt into passages and indexed, an invoice is
 * read into a table and fields and checked.
 */
const reader = [
  ["Isolated reader", "Own process with memory, CPU-time and wall-clock caps and no secrets"],
  ["Text layer", "PDFium: each line, and each table cell, with position, size and weight"],
  ["OCR for scans", "PP-OCRv6 small on CPU (ONNX Runtime); boxes deskewed"],
];

const questions = [
  ["Layout", "Headers and footers removed; headings and paragraphs rebuilt; page map kept"],
  ["Index", "~150-word passages in PostgreSQL full-text and pgvector (bge-small)"],
  ["Hybrid retrieval", "Keyword and vector rankings merged by reciprocal-rank fusion"],
  ["Answer", "Quoted with citations, or abstains; a model only through checked tools"],
];

const invoices = [
  ["Rows and table", "Header row by its column names, or the row above the first item"],
  ["Columns", "Bounded by the emptiest strip of the table; roles from heading or content"],
  ["Fields", "From labels, side by side or stacked; unknown labels by elimination"],
  ["Checks", "Quantity × price = amount; lines add up to the total; else review"],
];

function Steps({ title, steps, accent }: { title: string; steps: string[][]; accent?: boolean }) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-faint">{title}</p>
      <ol className="space-y-1.5">
        {steps.map(([name, note], i) => (
          <li
            key={name}
            className={`flex gap-3 rounded-sm px-3 py-2 ${
              accent ? "ring-1 ring-inset ring-line-strong" : "bg-surface-2"
            }`}
          >
            <span className="num w-4 shrink-0 text-xs text-faint">{i + 1}</span>
            <span>
              <span className="block font-medium text-text">{name}</span>
              <span className="block text-xs text-muted">{note}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function DocsArchitecture() {
  return (
    <figure className="rounded-md border border-line bg-surface p-5 text-sm">
      <div className="grid gap-4 md:grid-cols-3">
        <Steps title="Every PDF (upload, sample or invoice)" steps={reader} />
        <Steps title="To ask questions (worker, then API)" steps={questions} accent />
        <Steps title="To read an invoice (API, under the CPU lease)" steps={invoices} accent />
      </div>
      <p className="mt-4 text-xs text-muted">
        <span className="font-medium text-text">Privacy.</span> A PDF for questions waits in memory
        (a tmpfs shared by the API and worker) until it is read, then is discarded; its text and
        passages are deleted after an hour, or at once with “Delete now”. An invoice upload is read
        in memory and only the result is returned. Passages go to a hosted model only if the visitor
        ticks the box.
      </p>
      <figcaption className="sr-only">
        Every PDF is read in an isolated process using the text layer or OCR. For questions, it is
        rebuilt into headings and passages, indexed for keyword and vector search, and answers quote
        the retrieved passages with page citations. For invoices, the cells are grouped into rows
        and columns, header fields are read from their labels, and arithmetic checks decide whether
        the result needs review.
      </figcaption>
    </figure>
  );
}
