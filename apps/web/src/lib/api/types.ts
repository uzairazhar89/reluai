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

/** RFC 9457 problem details returned by the API on errors. */
export interface Problem {
  status: number;
  title?: string;
  detail?: string;
  code?: string;
  request_id?: string;
}
