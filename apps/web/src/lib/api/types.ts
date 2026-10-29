import type { components } from "./schema";

type S = components["schemas"];

export type Summary = S["SummaryOut"];
export type Run = S["RunOut"];
export type RunDetail = S["RunDetailOut"];
export type Step = S["StepOut"];
export type Check = S["DqOut"];
export type ReasonCount = S["ReasonCount"];
export type LogLine = S["LogOut"];
export type QuarantinePage = S["QuarantinePage"];
export type QuarantineRow = S["QuarantineRowOut"];
export type Scenario = S["ScenarioOut"];
export type Drop = S["DropOut"];
export type TrendPoint = S["TrendPoint"];
export type Results = S["ResultsOut"];
export type DropResult = S["DropResult"];
export type SiteStatus = S["StatusOut"];
export type RunAccepted = S["RunAccepted"];

export type CsvDataset = S["DatasetOut"];
export type CsvColumn = S["ColumnOut"];
export type CsvFinding = S["FindingOut"];
export type AskRequest = S["AskRequest"];
export type AskResponse = S["AskResponse"];
export type ResultColumn = S["ResultColumn"];
export type CsvEvaluation = S["EvaluationOut"];
export type CsvEvaluationSet = S["EvaluationSet"];
export type CsvEvaluationItem = S["EvaluationItem"];
export type CsvUsage = S["UsageOut"];

export type SupportCatalogue = S["CatalogueOut"];
export type SupportScenario = S["SupportScenarioOut"];
export type SupportCustomer = S["CustomerOut"];
export type Conversation = S["ConversationOut"];
export type ConversationStep = S["TraceStepOut"];
export type TranscriptEntry = S["TranscriptOut"];
export type SupportEvaluationRun = S["EvaluationRunOut"];
export type PolicySection = S["PolicySectionOut"];

export type DocumentInfo = S["DocumentOut"];
export type DocumentOutlineEntry = S["OutlineOut"];
export type DocumentChunks = S["ChunksOut"];
export type DocumentChunk = S["ChunkOut"];
export type DocumentQuestion = S["QuestionRequest"];
export type DocumentAnswer = S["AnswerOut"];
export type DocumentPassage = S["PassageOut"];
export type DocumentQaRun = S["QaEvaluationRunOut"];
export type DocumentQaItem = S["QaEvaluationItemOut"];

export type InvoiceDocument = S["InvoiceDocumentOut"];
export type InvoiceGallery = S["InvoiceGalleryOut"];
export type InvoiceRun = S["InvoiceRunOut"];
export type InvoiceExtraction = S["InvoiceExtractionOut"];
export type InvoiceField = S["InvoiceFieldOut"];
export type InvoiceLine = S["InvoiceLineOut"];
export type InvoiceCheck = S["InvoiceCheckOut"];
export type InvoiceBox = S["InvoiceBoxOut"];
export type InvoicePage = S["InvoicePageOut"];
export type InvoiceComparison = S["InvoiceComparisonOut"];
export type InvoiceEvaluation = S["InvoiceEvaluationOut"];
export type InvoiceEvaluationItem = S["InvoiceEvaluationItemOut"];

export type BenchRegistry = S["BenchRegistryOut"];
export type BenchModel = S["BenchModelOut"];
export type BenchVariant = S["BenchVariantOut"];
export type BenchQuantisation = S["BenchQuantisationOut"];
export type BenchRun = S["BenchRunOut"];
export type BenchRunSummary = S["BenchRunSummaryOut"];
export type BenchResult = S["BenchResultOut"];
export type BenchLatency = S["BenchLatencyOut"];
export type BenchAgreement = S["BenchAgreementOut"];
export type BenchHardware = S["BenchHardwareOut"];
export type BenchSample = S["BenchSampleOut"];
export type BenchTry = S["BenchTryOut"];
export type BenchTryVariant = S["BenchTryVariantOut"];

/** RFC 9457 problem details returned by the API on errors. */
export interface Problem {
  status: number;
  title?: string;
  detail?: string;
  code?: string;
  request_id?: string;
}
