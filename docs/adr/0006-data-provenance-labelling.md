# 0006. Data provenance labelling

Date: 2026-10-04. Status: accepted.

## Context

A portfolio is only persuasive if a reviewer can trust it. Invented metrics, unlabelled
synthetic data or real organisations shown next to automated judgements would undermine
that trust and could cause legal or reputational problems.

## Decision

- Real data is shown with its real dates and values; nothing is shifted to look recent.
- Simulated faults and synthetic data are labelled where they appear ("Simulated fault",
  "Synthetic data").
- Every figure on the site comes from a recorded run on the server. Results sections read
  measured values from the API and state the environment they were measured in.
- People are never identifiable: customer IDs stay anonymous; faces and licence plates in
  video are blurred.
- Organisations are never named next to an automated judgement; stable codes are used.
- Demos are labelled as portfolio demonstrations, not client systems.

## Consequences

- Some numbers on the site change as the system runs, and pages say so.
- Claims that cannot be measured are not made.
