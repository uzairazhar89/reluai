"""Invoice extraction: invoices rendered from real retail records, read back into fields.

* ``records``: the real invoices (UCI Online Retail II) and the evaluation set drawn from
  them, which is also the ground truth.
* ``render`` and ``scan``: each invoice drawn as a PDF in a generated layout, and as a
  simulated scan.
* ``extract``: positioned text (text layer or OCR) → header fields, line items and totals,
  with the arithmetic checks that tell a reviewer whether to trust the result.
* ``evaluate``: field-by-field comparison with the records.
"""
