"""
erp_inventory/accounting.py — posts stock value movements to the general ledger.

Perpetual inventory: the Inventory account always equals the value of stock on hand.

    Receipt from supplier        Dr Inventory          Cr Goods received not invoiced
    Delivery to customer         Dr Cost of goods sold Cr Inventory
    Return to supplier           Dr Goods not invoiced Cr Inventory
    Return from customer         Dr Inventory          Cr Cost of goods sold
    Count / adjustment (gain)    Dr Inventory          Cr Inventory adjustments
    Count / adjustment (loss)    Dr Inventory adj.     Cr Inventory
    Scrap                        Dr Inventory adj.     Cr Inventory
    NRV write-down               Dr Write-down         Cr Inventory

Transfers between internal locations move value within Inventory and post nothing.

Accounts and the stock journal are created on first use, so a tenant without a
configured chart still records stock. Entries go through AccountingService.post_move,
which enforces double entry.
"""
from decimal import Decimal

from django.utils import timezone

CENT = Decimal("0.01")
ZERO = Decimal("0")

ACCOUNT_SPECS = {
    "inventory": ("130000", "Inventory", "asset_current"),
    "stock_input": ("210000", "Goods Received Not Invoiced", "liability_current"),
    "cogs": ("500000", "Cost of Goods Sold", "expense_direct_cost"),
    "adjustments": ("510000", "Inventory Adjustments", "expense"),
    "write_down": ("520000", "Inventory Write-down", "expense"),
}
JOURNAL_CODE = "STK"


def _account(key):
    from inventory_apps.erp_accounting.models import AccountAccount

    code, name, account_type = ACCOUNT_SPECS[key]
    account = AccountAccount.objects.filter(code=code).first()
    if account is None:
        account = AccountAccount.objects.create(code=code, name=name, account_type=account_type)
    return account


def _journal():
    from inventory_apps.erp_accounting.models import AccountJournal

    journal, _ = AccountJournal.objects.get_or_create(
        code=JOURNAL_CODE,
        defaults={"name": "Stock Journal", "journal_type": "general"},
    )
    return journal


def post_value(reference_name, lines, date=None):
    """
    Post one balanced entry. `lines` is a list of (account_key, debit, credit) with
    Decimal amounts; zero-value entries are skipped.
    """
    from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine
    from inventory_apps.erp_accounting.services import AccountingService

    lines = [
        (key, debit.quantize(CENT), credit.quantize(CENT))
        for key, debit, credit in lines
    ]
    total = sum((debit for _, debit, _ in lines), Decimal("0"))
    if total == 0:
        return None

    move = AccountMove.objects.create(
        move_type="entry",
        journal=_journal(),
        ref=reference_name,
        narration=f"Stock movement {reference_name}".strip(),
        date=date or timezone.localdate(),
    )
    for sequence, (key, debit, credit) in enumerate(lines, start=10):
        if debit == 0 and credit == 0:
            continue
        AccountMoveLine.objects.create(
            move=move,
            sequence=sequence,
            account=_account(key),
            name=reference_name,
            debit=debit,
            credit=credit,
        )
    AccountingService.post_move(move)
    return move


def post_transfer_value(src, dest, value, reference_name):
    """
    Value of a move between a stock location and an outside location.
    `src` and `dest` are StockLocation rows; `value` is quantity times unit cost.
    """
    if value == 0:
        return None
    src_internal = src.usage == "internal"
    dest_internal = dest.usage == "internal"

    if src_internal and dest_internal:
        return None
    if dest_internal and src.usage == "supplier":
        return post_value(reference_name, [("inventory", value, ZERO), ("stock_input", ZERO, value)])
    if dest_internal and src.usage == "customer":
        return post_value(reference_name, [("inventory", value, ZERO), ("cogs", ZERO, value)])
    if src_internal and dest.usage == "customer":
        return post_value(reference_name, [("cogs", value, ZERO), ("inventory", ZERO, value)])
    if src_internal and dest.usage == "supplier":
        return post_value(reference_name, [("stock_input", value, ZERO), ("inventory", ZERO, value)])
    return None


def post_adjustment_value(delta_value, reference_name):
    """A gain (positive) or loss (negative) of stock value from a count or adjustment."""
    if delta_value == 0:
        return None
    if delta_value > 0:
        return post_value(reference_name, [("inventory", delta_value, ZERO), ("adjustments", ZERO, delta_value)])
    loss = -delta_value
    return post_value(reference_name, [("adjustments", loss, ZERO), ("inventory", ZERO, loss)])


def post_scrap_value(value, reference_name):
    return post_adjustment_value(-value, reference_name)


def post_write_down(total, reference_name):
    return post_value(reference_name, [("write_down", total, ZERO), ("inventory", ZERO, total)])

