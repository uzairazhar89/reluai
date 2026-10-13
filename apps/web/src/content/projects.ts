/**
 * Every flagship project, live or not. Only projects with status "live" get a card and a page;
 * the rest are listed as roadmap items so the site never presents unbuilt work as available.
 */
export type ProjectStatus = "live" | "building" | "planned";
export type Role = "Data engineering" | "AI and LLM apps" | "Computer vision" | "Research";

export interface Project {
  slug: string;
  title: string;
  status: ProjectStatus;
  roles: Role[];
  oneLiner: string;
  problem: string;
  solution: string;
  tech: string[];
  repoPath: string;
  dataNote?: string;
}

export const projects: Project[] = [
  {
    slug: "data-pipeline-observatory",
    title: "Data Pipeline Observatory",
    status: "live",
    roles: ["Data engineering"],
    oneLiner: "ETL on a real retailer's invoices, with quality gates and a run-by-run audit trail.",
    problem:
      "Monthly exports, a product master and a CRM API never agree. Duplicates, cancellations, " +
      "stock write-offs and missing customer IDs silently corrupt every report built on them.",
    solution:
      "A Python pipeline that validates each row against a data contract, quarantines bad rows " +
      "with reason codes, loads PostgreSQL idempotently and refuses to publish when a quality " +
      "gate fails.",
    tech: ["Python", "pandas", "PostgreSQL", "FastAPI", "Procrastinate", "Docker"],
    repoPath: "projects/pipeline-observatory",
    dataNote: "Real data: UCI Online Retail II (CC BY 4.0)",
  },
  {
    slug: "ai-csv-analyst",
    title: "AI CSV Analyst",
    status: "live",
    roles: ["AI and LLM apps", "Data engineering"],
    oneLiner: "Upload a CSV, get a quality report, ask questions in plain English, see the SQL.",
    problem:
      "Chat-with-your-data tools write SQL nobody reads, answer confidently when the question " +
      "does not fit the data, and say nothing about the duplicates and gaps that skew totals.",
    solution:
      "Profiles the table first, turns each question into a validated query plan (rules first, " +
      "an optional LLM second), runs it in a locked-down DuckDB sandbox and shows the SQL.",
    tech: ["DuckDB", "Python", "function calling", "FastAPI", "Next.js"],
    repoPath: "projects/csv-analyst",
    dataNote: "Real data: UCI Online Retail II (CC BY 4.0)",
  },
  {
    slug: "document-intelligence",
    title: "Document Q&A",
    status: "live",
    roles: ["AI and LLM apps"],
    oneLiner: "Upload any PDF and ask questions; answers quote the document with page citations.",
    problem:
      "Answers from long documents are only useful if you can check them. Chatbots over PDFs " +
      "paraphrase without saying where, invent what the document does not say, and break on " +
      "scanned pages.",
    solution:
      "Reads the PDF in an isolated process (text layer or OCR), rebuilds headings and pages, " +
      "searches by keywords and meaning, and answers only from cited passages, or says the " +
      "document does not cover it.",
    tech: ["PDFium", "OCR (ONNX)", "pgvector", "PostgreSQL full-text", "FastAPI", "Next.js"],
    repoPath: "projects/document-intelligence",
    dataNote: "Your PDF, or a real NIST publication",
  },
  {
    slug: "support-agent",
    title: "Customer Support Agent",
    status: "live",
    roles: ["AI and LLM apps"],
    oneLiner: "A tool-calling agent that resolves order questions, with approval before refunds.",
    problem:
      "Order questions are repetitive and costly to get wrong; prompt-only chatbots invent " +
      "order details, promise refunds the policy does not allow and can be talked into things.",
    solution:
      "An agent loop over real invoices with validated tools, refund rules in code, cited " +
      "policy passages, supervisor approval above £50 and a trace of every step.",
    tech: ["function calling", "agent loop", "PostgreSQL full-text search", "FastAPI", "Next.js"],
    repoPath: "projects/support-agent",
    dataNote: "Real invoices; simulated shipments and policy",
  },
  {
    slug: "edge-ai-benchmark-lab",
    title: "Edge AI Benchmark Lab",
    status: "planned",
    roles: ["Computer vision"],
    oneLiner: "PyTorch vs ONNX vs INT8 on CPU: latency, memory and accuracy, measured.",
    problem: "",
    solution: "",
    tech: ["PyTorch", "ONNX Runtime", "quantisation"],
    repoPath: "projects/edge-bench",
  },
  {
    slug: "invoice-matching",
    title: "Invoice Matching Agent",
    status: "planned",
    roles: ["AI and LLM apps", "Data engineering"],
    oneLiner: "Reconciles public-sector payments against contract awards and explains exceptions.",
    problem: "",
    solution: "",
    tech: ["entity resolution", "function calling"],
    repoPath: "projects/invoice-matching",
  },
  {
    slug: "research-search",
    title: "Research Search Intelligence",
    status: "planned",
    roles: ["Research", "AI and LLM apps"],
    oneLiner: "From a clinical research question to concepts, MeSH terms and ranked papers.",
    problem: "",
    solution: "",
    tech: ["hybrid search", "MeSH", "pgvector"],
    repoPath: "projects/research-search",
  },
  {
    slug: "street-scene",
    title: "Street Scene Intelligence",
    status: "planned",
    roles: ["Computer vision"],
    oneLiner: "Detection, tracking, pose and pedestrian crossing-intent on open street footage.",
    problem: "",
    solution: "",
    tech: ["detection", "tracking", "pose estimation"],
    repoPath: "projects/street-scene",
  },
];

export const liveProjects = projects.filter((p) => p.status === "live");
export const upcomingProjects = projects.filter((p) => p.status !== "live");

export const statusLabel: Record<ProjectStatus, string> = {
  live: "Live",
  building: "In build",
  planned: "Planned",
};
