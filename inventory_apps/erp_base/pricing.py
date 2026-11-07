"""
erp_base/pricing.py — shared line-total math for every order/invoice line
model (sales, purchase, POS, accounting). Centralized so "tax included in
price" (Tax.price_include) is computed identically everywhere.
"""
from decimal import Decimal


def compute_line_amounts(price_unit, qty, discount_pct, taxes):
    """Given a line's price_unit/qty/discount% and its taxes, returns
    (price_subtotal, tax_amount, price_total) — the untaxed amount, total
    tax, and tax-inclusive total.

    Taxes with `price_include=True` are treated as already baked into
    `price_unit` (Odoo's "Included in Price" checkbox): their amount is
    peeled back OUT of the discounted line amount to find the untaxed
    subtotal. Taxes with `price_include=False` are added on top of that
    subtotal, as before. Mixing both on one line applies included taxes
    first, then excluded taxes on the resulting (smaller) base — matching
    Odoo's own sequential behavior for the common, non-compounding case.
    """
    gross = price_unit * qty
    discount = gross * (discount_pct / Decimal("100"))
    line_amount = (gross - discount).quantize(Decimal("0.01"))

    taxes = list(taxes)
    included = [t for t in taxes if t.price_include]
    excluded = [t for t in taxes if not t.price_include]

    included_tax_amount = Decimal("0.00")
    for tax in included:
        included_tax_amount += tax.compute_amount(line_amount)

    price_subtotal = (line_amount - included_tax_amount).quantize(Decimal("0.01"))

    excluded_tax_amount = Decimal("0.00")
    for tax in excluded:
        excluded_tax_amount += tax.compute_amount(price_subtotal)

    tax_amount = (included_tax_amount + excluded_tax_amount).quantize(Decimal("0.01"))
    price_total = (price_subtotal + tax_amount).quantize(Decimal("0.01"))
    return price_subtotal, tax_amount, price_total
