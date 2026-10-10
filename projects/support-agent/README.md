# Customer Support Agent

A tool-calling agent that answers order questions from a real retailer's customers about
their real invoices. It looks up the invoice and the tracking, searches the service policy,
asks the refund rules what is due, records refunds within its limit, asks a supervisor for
anything larger, opens tickets for people and drafts a reply that cites the policy. Every
step is traced. Nothing is sent and no money moves. Live demo:
<https://reluai.cloud/projects/support-agent>.

**Real:** customers (anonymous IDs), invoices, products, quantities and prices from
[UCI Online Retail II](https://doi.org/10.24432/C5CG6D) (CC BY 4.0).
**Simulated, and labelled:** shipments, the service policy, tickets, refunds and messages.

## How it works

```
customer message ─► agent loop (≤ 8 steps, ≤ 25 s) ─► provider chain
                       │   ▲                          Groq → Cerebras (free tiers, if keys
                       │   │ results / errors          are set) → scripted agent
                       ▼   │
            tools (validated arguments, one customer only)
            get_invoice · list_customer_invoices · get_shipment_status · search_policy
            calculate_refund · request_approval · create_ticket · draft_reply
                       │
                       └─► refund > £50 ─► conversation pauses ─► supervisor decides ─► resume
```

- **Agent loop** (`agent.py`): written by hand against the OpenAI-compatible chat API.
  Each step sends the conversation and tool definitions; every tool call in the response
  runs (several per step), results and validation errors go back to the model. A turn ends
  with `draft_reply`, a pending approval, or the step/time budget, after which the case is
  handed to a person with a ticket. Each step is traced with provider, model, tokens and
  latency.
- **Tools** (`tools.py`): Pydantic argument models; every lookup is scoped to the
  conversation's customer, and another customer's invoice is indistinguishable from a
  missing one.
- **Refund rules** (`refunds.py`): damaged or missing items within 14 days of delivery,
  late deliveries (shipping charge, or 5% of the goods up to £10), lost parcels (10 days
  past the estimate), returns within 30 days (refunded on receipt), never on credit notes.
  `request_approval` accepts only the amount `calculate_refund` returned.
- **Policy** (`policy.py`): written for the demo, indexed with `packages/retrieval`
  (PostgreSQL full-text search); replies may only cite passages the agent retrieved.
- **Orders** (`orders.py`): a read-only DuckDB snapshot of the invoice lines of customers
  with an ID (797,885 lines after removing the export's duplicate lines), built when the
  image is built.
- **Shipments** (`shipments.py`): simulated deterministically from each invoice's number
  and date (about 86% on time, 8% late, 4% lost, 2% returned), with generic carrier
  names. The desk works as of 10 December 2011, the day after the data ends.
- **Scripted agent** (`scripted.py`): the last provider in the chain. It reads keywords
  and product names and follows a fixed procedure with the same tools, so the demo works
  with no model. It is labelled wherever it answers.

## Results

44 scenarios on real invoices (`scenarios.py`): damaged and missing items inside and
outside the window, late and lost parcels, parcels in transit or returned to sender,
returns, credit notes, invoice questions, messages without an invoice number, another
customer's invoice and two prompt-injection attempts. A scenario passes only if the refunds
recorded (amount computed from the rules for the expected items), approvals, tickets,
reply and tools used are all as expected.

| Agent | Passed | Measured |
| --- | --- | --- |
| Scripted agent (no model) | 44 of 44 | 10 October 2026, local run |

The scripted agent was written alongside the scenarios, so its result checks that the
tools, rules, approval flow and trace work end to end; it is not evidence of language
understanding. No model has been scored yet: the server runs without one by default. With a
free-tier key configured:

```bash
reluai-support evaluate --provider groq        # records the run unless a provider outage occurred
```

## Run it

```bash
uv run reluai-data fetch online-retail-ii --out data/canonical
uv run reluai-support build-data --canonical-dir data/canonical --out data/support
RELUAI_SUPPORT_DATA_DIR=data/support uv run reluai-support ask 18249 \
  "My order 578058 arrived and 2 of the fawn blue hot water bottles were cracked."
RELUAI_SUPPORT_DATA_DIR=data/support uv run reluai-support evaluate --no-record
```

API (mounted at `/api/support`): `GET /catalogue`, `GET /policy`, `POST /conversations`,
`GET /conversations/{id}`, `POST /conversations/{id}/messages`,
`POST /conversations/{id}/approval`, `GET /evaluation`.

## Tests

- Refund rules, shipment simulation and message reading (unit).
- Tools: customer scoping, amounts only from the rules, the approval limit, citations only
  to retrieved passages.
- The loop with a fake model: invalid arguments and unknown tools corrected after the error
  is returned, text answers, step-limit hand-over, fallback to the scripted agent.
- API against PostgreSQL: approval flow, ownership, quotas, recorded evaluations.
- The full scenario suite on the real data (`slow`, in CI's datasets job).

## Limitations

- The scripted agent handles the phrasings it was written for and simple variations.
- Credit notes in the source data do not reference the invoice they credit, so earlier
  refunds on the same items cannot be checked.
- One customer per conversation, chosen in the demo; a real system would take it from an
  authenticated session.

Portfolio demonstration. Data: Chen, D. (2012). Online Retail II [Dataset]. UCI Machine
Learning Repository, CC BY 4.0.
