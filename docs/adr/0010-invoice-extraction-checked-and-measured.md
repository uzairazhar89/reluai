# 0010. Invoices are read by geometry and checked by arithmetic, and measured against real records

Date: 2026-10-14. Status: accepted.

## Context

The second part of Document Intelligence (P5) reads invoices into structured fields. Three
things make that hard to do honestly in a portfolio:

- **Ground truth.** Real invoice documents under an open licence essentially do not exist,
  and a demo built on a handful of hand-made samples proves nothing.
- **Unknown layouts.** Every supplier's software lays invoices out differently. An
  extractor tuned on the layouts it is tested on will look perfect and generalise badly.
- **Silent errors.** An extracted total that is wrong and looks right is worse than no
  extraction: it gets paid.

The budget is $0 and the demo must work without a language model (ADR-0005).

## Decision

1. **Test documents from real records.** Invoices are drawn from UCI Online Retail II
   (real invoice lines of a real, anonymised retailer, CC BY 4.0) and rendered as PDFs, so
   every value is known exactly. A share is turned into simulated scans (rasterised,
   rotated, noised, JPEG-compressed). Every page says it is a rendering of dataset records.
2. **Layouts from a generator, with a held-out half.** Each document's layout (wording,
   column order, formats, fonts, rules, page breaks) is generated from a seed. Development
   used one set of seeds; the other half of the invoices uses seeds that were not looked at
   until the extractor was finished, and some wordings that exist only in those layouts.
   Results are published per group, and the held-out groups are the estimate.
3. **Geometry, not a model.** The reader keeps table cells and labels as separate pieces
   with positions (using PDFium's record of which spaces are real, or OCR boxes). The
   extractor finds the table's header row, sets column boundaries at the emptiest strip of
   the table body, assigns roles from headings or, when a heading is unfamiliar, from the
   column's content, and reads header fields from labels or by elimination.
4. **Checks, never silent fixes.** Quantity × unit price must equal each amount, the amounts
   must add up to the total, the number and date must be present, and the total's sign must
   fit the document type. A failed check flags the result for review; values are never
   "repaired". The evaluation reports how many wrong results were flagged and how many were
   not ("silently wrong").
5. **Same path as uploads.** Live runs, uploads and the daily evaluation read through the
   isolated reader (ADR-0009) under the CPU lease; uploaded invoices are not stored.

## Consequences

- Accuracy is measured, not estimated, and the gap between development and held-out
  layouts is visible. The held-out layouts still come from the same generator, so they
  test unseen combinations and some unseen wording, not the full variety of real suppliers.
- The arithmetic checks catch misread numbers but not misread text: an OCR error in a
  description passes them. Comparing codes and descriptions with a product master would
  catch those; there is none for uploads.
- An optional model (schema-constrained output, same checks) could be added and scored on
  the same set; it is not needed for the generated layouts and is not built yet.
- FATURA (synthetic invoice images in 50 layouts) remains a candidate for a harder,
  independent layout test.
