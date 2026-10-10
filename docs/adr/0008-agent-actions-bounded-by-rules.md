# 0008. Agents act through tools, with amounts from rules and a person above a limit

Date: 2026-10-11. Status: accepted.

## Context

The support agent (P7) can record refunds and open tickets. A model that decides amounts,
or acts on whatever a customer writes, is unsafe in operations; a demo that depends on a
paid or always-available model breaks the $0 budget.

## Decision

1. The agent loop is written by hand against the OpenAI-compatible chat API, so every step
   is visible and testable; no agent framework.
2. The model only proposes tool calls. Arguments are validated; every tool is scoped to the
   conversation's customer.
3. Money comes from rules in code: `request_approval` accepts only the amount
   `calculate_refund` returned. Up to £50 the agent records the refund itself; above that
   the conversation pauses until a person decides.
4. A turn has a step and time budget; when it runs out the case is handed to a person.
5. A scripted agent is the last provider in the chain, so the demo works with no model, and
   it is the baseline models are measured against on the same scenarios.
6. All actions are simulated records with a 24-hour life; nothing is sent or paid.

## Consequences

- A persuasive customer, a prompt injection or a confused model cannot change an amount or
  reach another customer's data; tests cover each.
- Model quality shows up as more or fewer steps, clarifying questions and hand-overs, not
  as wrong money.
- The scripted baseline's score reflects scenarios written alongside it and is presented
  that way; model scores are recorded only from runs without provider outages.
