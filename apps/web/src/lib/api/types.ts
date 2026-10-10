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

/** RFC 9457 problem details returned by the API on errors. */
export interface Problem {
  status: number;
  title?: string;
  detail?: string;
  code?: string;
  request_id?: string;
}
