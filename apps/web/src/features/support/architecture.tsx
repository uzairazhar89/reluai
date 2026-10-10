/**
 * The agent loop as an HTML flow: a model (or the scripted agent) proposes tool calls, the
 * tools run against real orders and the written policy, and refunds above the limit stop for
 * a person.
 */
const tools = [
  ["get_invoice", "Real invoice lines and totals"],
  ["list_customer_invoices", "The customer's recent orders"],
  ["get_shipment_status", "Simulated tracking for the invoice"],
  ["search_policy", "Full-text search, numbered passages"],
  ["calculate_refund", "Policy rules in code: eligibility and amount"],
  ["request_approval", "Records a refund; over £50 waits for a supervisor"],
  ["create_ticket", "Hands work to a person"],
  ["draft_reply", "Saves the reply; nothing is sent"],
];

export function SupportArchitecture() {
  return (
    <figure className="rounded-md border border-line bg-surface p-5 text-sm">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="space-y-2">
          <div className="rounded-sm bg-surface-2 px-3 py-2.5">
            <p className="font-medium text-text">Customer message</p>
            <p className="mt-1 text-xs text-muted">About one of their real invoices</p>
          </div>
          <div className="rounded-sm px-3 py-2.5 ring-1 ring-inset ring-link/50">
            <p className="font-medium text-text">Agent loop</p>
            <p className="mt-1 text-xs text-muted">
              Up to 8 steps and 25 seconds a turn. Each step: the model sees the conversation and
              the tools, proposes calls; arguments are validated, tools run, results go back.
            </p>
          </div>
          <div className="rounded-sm px-3 py-2.5 ring-1 ring-inset ring-line-strong">
            <p className="font-medium text-text">Provider chain</p>
            <p className="mt-1 text-xs text-muted">
              Groq, then Cerebras (free tiers, when keys are set), then the scripted agent. Token
              budgets per day and per visitor.
            </p>
          </div>
        </div>
        <ul className="grid gap-1.5 sm:grid-cols-2" aria-label="Tools">
          {tools.map(([name, note]) => (
            <li key={name} className="rounded-sm bg-surface-2 px-3 py-2">
              <p className="font-mono text-[0.8125rem] text-text">{name}</p>
              <p className="text-xs text-muted">{note}</p>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-4 grid gap-3 border-t border-line pt-4 md:grid-cols-3">
        <p className="text-xs text-muted">
          <span className="font-medium text-pass">Real.</span> Customers (anonymous IDs), invoices,
          products, quantities and prices from UCI Online Retail II.
        </p>
        <p className="text-xs text-muted">
          <span className="font-medium text-warn">Simulated.</span> Shipments, the service policy,
          tickets, refunds and the messages themselves. Nothing leaves the system.
        </p>
        <p className="text-xs text-muted">
          <span className="font-medium text-text">Human in the loop.</span> A refund above £50
          pauses the conversation until the supervisor (you) approves or rejects it.
        </p>
      </div>
      <figcaption className="sr-only">
        A customer message goes to an agent loop that calls a provider chain: free-tier models when
        configured, then a scripted agent. The agent uses eight tools over real invoices, simulated
        shipments and a written policy; refunds above £50 wait for a supervisor.
      </figcaption>
    </figure>
  );
}
