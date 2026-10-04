import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Run } from "@/lib/api/types";
import { NowProvider } from "@/lib/now";

import { RunsTable } from "./runs-table";

const base: Run = {
  id: "a",
  scenario: "standard",
  trigger: "scheduled",
  simulated: false,
  status: "succeeded",
  drop_key: "2010-12",
  queued_at: "2026-10-04T11:54:30Z",
  started_at: "2026-10-04T11:54:30Z",
  finished_at: "2026-10-04T11:54:33Z",
  duration_ms: 2376,
  rows_read: 65004,
  rows_accepted: 41713,
  rows_rejected: 447,
  rows_deduplicated: 22844,
  rows_warned: 16626,
  rows_inserted: 41713,
  rows_unchanged: 0,
  source_retries: 0,
  dq_score: 90,
  failure_step: null,
  error_message: null,
  note: null,
};

const runs: Run[] = [
  { ...base, id: "q", status: "queued", trigger: "visitor", started_at: null, rows_read: 0 },
  base,
];

function renderTable(onSelect = vi.fn()) {
  render(
    <NowProvider serverNow="2026-10-04T12:00:00Z">
      <RunsTable runs={runs} selectedId="a" onSelect={onSelect} scenarioTitle={() => "Load next"} />
    </NowProvider>,
  );
  return onSelect;
}

describe("RunsTable", () => {
  // After hydration the shared clock reads the real time, so pin it.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-04T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("marks the selected run and reports clicks", async () => {
    const onSelect = renderTable();
    const buttons = screen.getAllByRole("button", { name: /Load next/ });
    expect(buttons[1]).toHaveAttribute("aria-current", "true");
    await userEvent.click(buttons[0]!);
    expect(onSelect).toHaveBeenCalledWith("q");
  });

  it("shows figures only for finished runs", () => {
    renderTable();
    expect(screen.getAllByText("65,004").length).toBeGreaterThan(0);
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText(/December 2010, 6 minutes ago, scheduled/)).toBeInTheDocument();
  });

  it("invites a first run when empty", () => {
    render(<RunsTable runs={[]} selectedId={null} onSelect={vi.fn()} scenarioTitle={String} />);
    expect(screen.getByText(/No runs yet/)).toBeInTheDocument();
  });
});
