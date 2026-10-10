# 0007. Questions become validated query plans, never generated SQL

Date: 2026-10-10. Status: accepted.

## Context

The AI CSV Analyst answers questions about a real table and about files visitors upload.
The common way to build this is to let a language model write SQL or pandas code and run
it. That makes the system only as safe as the model's output, hides what was computed from
the reader, and fails silently when the question does not fit the data. The site also has
no paid model: a free-tier provider may be missing or exhausted at any moment.

## Decision

1. An interpreter produces a **query plan**, a small Pydantic model (measures, groupings,
   a time bucket, filters, sort, limit). It cannot express anything else: no joins, no
   subqueries, no free text that reaches SQL.
2. A **rule-based parser** is the first interpreter. It declines any question containing a
   word it does not understand, instead of guessing.
3. A **language model** is the second interpreter, only when the rules decline, through
   one function call whose arguments are the plan's JSON Schema. Validation problems are
   returned as the tool result for at most 2 retries.
4. Every plan, from either source, goes through the same **validator** (columns, types,
   values as spelled in the data) and **compiler** (quoted identifiers, bound parameters).
5. Compiled SQL runs in a **DuckDB sandbox**: read-only, no file or network access, no
   extensions, locked configuration, memory and time limits.
6. The answer always shows the plan as a sentence, the SQL and the pandas equivalent.

## Consequences

- No question or model output can modify, exfiltrate or reach beyond the table; this is
  tested with hostile SQL sent directly to the sandbox.
- The analyst works with no model at all, at $0.
- Capability is deliberately limited: aggregate questions only. Row listings, shares,
  ratios and filters on aggregates are declined; extending the plan is a code change with
  tests, not a prompt change.
- The rules need maintenance as phrasings are added, and their coverage is measured on a
  held-out question set that is never used to tune them.
