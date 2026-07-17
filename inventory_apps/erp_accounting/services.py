"""
erp_accounting/services.py — AccountingService: post journal entries, register payments,
reconcile, compute trial balance.
All posted moves must satisfy sum(debit) == sum(credit).
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone


class AccountingService:

    @classmethod
    @transaction.atomic
    def post_move(cls, move):
        """Post a journal entry / invoice. Validates double-entry balance for journal entries."""
        from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine, AccountAccount

        if move.state == "posted":
            raise ValueError("Move is already posted")

        if move.move_type == "entry":
            # Pure journal entry: must balance
            lines = move.lines.all()
            total_debit = sum(l.debit for l in lines) or Decimal("0.00")
            total_credit = sum(l.credit for l in lines) or Decimal("0.00")
            if abs(total_debit - total_credit) > Decimal("0.01"):
                raise ValueError(
                    f"Journal entry does not balance: debit={total_debit}, credit={total_credit}"
                )
        else:
            # Invoice/Bill: build accounting lines automatically
            cls._generate_accounting_lines(move)

        move.state = "posted"
        if not move.name:
            from inventory_apps.erp_base.models import SequenceCounter
            prefix_map = {
                "out_invoice": "INV",
                "in_invoice": "BILL",
                "out_refund": "RINV",
                "in_refund": "RBILL",
                "entry": "JE",
            }
            move.name = SequenceCounter.next_sequence(prefix_map.get(move.move_type, "JE"))
        if not move.invoice_date:
            move.invoice_date = timezone.now().date()
        move.save(update_fields=["state", "name", "invoice_date"])
        move.compute_totals()
        return move

    @classmethod
    def _generate_accounting_lines(cls, move):
        """
        For invoices, create the counterpart receivable/payable line automatically.
        Invoice tab lines (exclude_from_invoice_tab=False) already exist.
        We add one counterpart line for the total amount.
        """
        from inventory_apps.erp_accounting.models import AccountAccount, AccountMoveLine

        if move.move_type in ("out_invoice", "out_refund"):
            account_type = "asset_receivable"
            sign = 1 if move.move_type == "out_invoice" else -1
        else:
            account_type = "liability_payable"
            sign = 1 if move.move_type == "in_invoice" else -1

        counterpart_account = AccountAccount.objects.filter(
            account_type=account_type, active=True
        ).first()
        if not counterpart_account:
            return

        # Delete any existing counterpart line so we don't duplicate
        move.lines.filter(exclude_from_invoice_tab=True).delete()

        total = sum(
            l.price_subtotal + l.tax_amount
            for l in move.lines.filter(exclude_from_invoice_tab=False)
        ) or Decimal("0.00")

        if total == Decimal("0.00"):
            return

        if move.move_type in ("out_invoice", "in_refund"):
            debit = total * sign if sign > 0 else Decimal("0.00")
            credit = abs(total * sign) if sign < 0 else Decimal("0.00")
        else:
            debit = Decimal("0.00")
            credit = total

        AccountMoveLine.objects.create(
            move=move,
            account=counterpart_account,
            partner=move.partner,
            name=f"Counterpart: {move.partner.name if move.partner else ''}",
            debit=debit if move.move_type in ("out_invoice",) else Decimal("0.00"),
            credit=credit if move.move_type in ("out_invoice",) else total,
            exclude_from_invoice_tab=True,
            date_maturity=move.invoice_date_due,
        )

    @classmethod
    @transaction.atomic
    def register_payment(cls, move, amount: Decimal, journal, date=None, memo: str = ""):
        """Register a payment against an invoice and partially/fully reconcile."""
        from inventory_apps.erp_accounting.models import AccountPayment, AccountMove, AccountMoveLine, AccountAccount

        if move.state != "posted":
            raise ValueError("Can only pay posted invoices")

        payment_type = "inbound" if move.move_type in ("out_invoice",) else "outbound"
        partner_type = "customer" if move.move_type in ("out_invoice",) else "supplier"

        payment = AccountPayment.objects.create(
            payment_type=payment_type,
            partner_type=partner_type,
            partner=move.partner,
            journal=journal,
            amount=amount,
            date=date or timezone.now().date(),
            memo=memo or move.name,
            reconcile_move=move,
            currency=move.currency,
        )

        # Create a payment journal entry
        if payment_type == "inbound":
            debit_account = journal.default_account
            credit_account = AccountAccount.objects.filter(
                account_type="asset_receivable", active=True
            ).first()
        else:
            debit_account = AccountAccount.objects.filter(
                account_type="liability_payable", active=True
            ).first()
            credit_account = journal.default_account

        if debit_account and credit_account:
            pay_move = AccountMove.objects.create(
                move_type="entry",
                journal=journal,
                partner=move.partner,
                date=payment.date,
                narration=memo,
                state="draft",
            )
            AccountMoveLine.objects.create(
                move=pay_move, account=debit_account, partner=move.partner,
                debit=amount, credit=Decimal("0.00"),
                name=f"Payment: {move.name}", exclude_from_invoice_tab=True,
            )
            AccountMoveLine.objects.create(
                move=pay_move, account=credit_account, partner=move.partner,
                debit=Decimal("0.00"), credit=amount,
                name=f"Payment: {move.name}", exclude_from_invoice_tab=True,
            )
            pay_move.state = "posted"
            pay_move.save(update_fields=["state"])
            payment.move = pay_move
            payment.save(update_fields=["move"])

        # Update invoice paid amount
        move.amount_paid = (move.amount_paid or Decimal("0.00")) + amount
        move.amount_residual = max(move.amount_total - move.amount_paid, Decimal("0.00"))
        if move.amount_residual <= Decimal("0.00"):
            move.payment_state = "paid"
        elif move.amount_paid > Decimal("0.00"):
            move.payment_state = "partial"
        move.save(update_fields=["amount_paid", "amount_residual", "payment_state"])
        payment.state = "reconciled"
        payment.save(update_fields=["state"])
        return payment

    @classmethod
    def post_payment(cls, payment):
        from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine, AccountAccount
        if payment.state != "draft":
            raise ValueError("Payment already posted")
        payment.state = "posted"
        if not payment.name:
            from inventory_apps.erp_base.models import SequenceCounter
            prefix = "PAY/IN" if payment.payment_type == "inbound" else "PAY/OUT"
            payment.name = SequenceCounter.next_sequence(prefix)
        payment.save(update_fields=["state", "name"])
        return payment

    @classmethod
    def get_trial_balance(cls, date_from=None, date_to=None):
        from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine, AccountAccount
        from django.db.models import Sum, Q

        qs = AccountMoveLine.objects.filter(move__state="posted")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

        return (
            qs.values(
                "account__code",
                "account__name",
                "account__account_type",
            )
            .annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit"),
            )
            .order_by("account__code")
        )

    @classmethod
    def get_profit_and_loss(cls, date_from=None, date_to=None):
        tb = cls.get_trial_balance(date_from, date_to)
        income = Decimal("0.00")
        expense = Decimal("0.00")
        lines = []
        for row in tb:
            at = row["account__account_type"]
            balance = (row["total_credit"] or Decimal("0.00")) - (
                row["total_debit"] or Decimal("0.00")
            )
            if at.startswith("income"):
                income += balance
                lines.append({**row, "balance": balance, "section": "income"})
            elif at.startswith("expense"):
                expense += abs(balance)
                lines.append({**row, "balance": balance, "section": "expense"})
        return {
            "lines": lines,
            "total_income": income,
            "total_expense": expense,
            "net_profit": income - expense,
        }
