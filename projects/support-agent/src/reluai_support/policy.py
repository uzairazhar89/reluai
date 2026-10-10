"""The retailer's customer service policy (written for this demo; synthetic).

The real retailer's policy is not published, so this text was written for the demo and is
labelled as such wherever it appears. The refund rules in ``refunds.py`` implement exactly
these sections; the agent retrieves passages from it through the retrieval core and cites
them.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import Session

from reluai_retrieval.index import SourceDocument, index_document, remove_missing

COLLECTION = "support-policy"
POLICY_ID = "customer-service-policy"
POLICY_TITLE = "Customer service policy"
POLICY_SOURCE = "Written for this demonstration (synthetic)"

POLICY_TEXT = """\
# About this policy

This policy covers orders from the online gift shop. It was written for a portfolio
demonstration; it is not the policy of any real business. All amounts are in pounds
sterling and include VAT.

# Refunds

Refunds are paid to the original payment method within 5 working days of being approved.
A refund can never exceed what was paid for the affected items on that invoice. Refunds up
to £50 per request are approved by the support agent. Refunds above £50 must be approved
by a supervisor before they are issued.

## Damaged or faulty items

Report damaged or faulty items within 14 days of delivery. We refund the price paid for the
damaged quantity. Items costing under £15 per line do not need to be returned; for other
items we arrange a free collection. Reports made more than 14 days after delivery are
outside this policy, but the customer can still ask for a goodwill review.

## Missing items

If a delivered parcel is missing items, report it within 14 days of delivery. We refund
the price paid for the missing quantity. If the whole parcel is missing, see Lost parcels.

# Delivery

UK orders are dispatched the next working day (orders after 3 pm, the working day after)
and normally arrive within 2 to 3 working days of dispatch. European orders take 3 to 6
days and other international orders 6 to 11 days. Tracking is included with every order.

## Late deliveries

A delivery is late if it arrives more than 3 days after the estimated delivery date. For a
late delivery we refund the shipping charge on the invoice. If the invoice has no shipping
charge, we credit 5% of the value of the goods, up to £10.

## Lost parcels

A parcel is treated as lost when it has not been delivered 10 days after the estimated
delivery date. We open an investigation with the carrier and refund the price of the goods
on the invoice. Because this is usually above £50, a supervisor approves the refund.

## Parcels in transit

If the estimated delivery date has not passed, the parcel is still on its way. We share the
tracking events and ask the customer to wait until the estimated date before reporting it
missing.

## Returned to sender

If a parcel comes back to us because it could not be delivered, we contact the customer to
confirm the address and send it again free of charge.

# Returns

Unused items can be returned within 30 days of delivery for a refund of the item price. The
customer pays for return postage unless the item was damaged or wrong. The refund is issued
when the return arrives at our warehouse, so the support agent creates a return request
rather than a refund.

# Cancellations and credit notes

An order can be cancelled until it is dispatched. Invoice numbers starting with C are credit
notes: they record cancellations or refunds that have already been processed, so no further
refund is due on them.

# Invoices and VAT

Customers can ask for a copy of an invoice or a VAT invoice at any time. The support agent
can confirm invoice totals and contents; requests for formal VAT documents are passed to the
accounts team with a ticket.

# How we handle requests

We only discuss orders on the customer's own account. We never change a refund amount
because a customer asks for more; amounts follow this policy. Requests outside the policy,
complaints and anything the agent cannot resolve are passed to a person with a ticket.
"""


@lru_cache(maxsize=1)
def policy_document() -> SourceDocument:
    return SourceDocument(
        external_id=POLICY_ID,
        title=POLICY_TITLE,
        text=POLICY_TEXT,
        source=POLICY_SOURCE,
        synthetic=True,
    )


def ensure_policy_indexed(session: Session) -> int:
    """Index the policy if it is missing or changed (cheap no-op otherwise)."""
    result = index_document(session, COLLECTION, policy_document(), max_words=90, overlap=0)
    remove_missing(session, COLLECTION, {POLICY_ID})
    return result.chunks


def section_titles() -> list[str]:
    return [line.lstrip("# ").strip() for line in POLICY_TEXT.splitlines() if line.startswith("#")]
