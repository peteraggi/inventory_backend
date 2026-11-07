# inventory_apps/erp_pos/services.py

"""
POSService: take payment, open and close registers, sync offline sales.

Paying an order does three things in one transaction: reduces stock for storable
products, posts the sale to the ledger (cash in, revenue and tax out), and marks the
order paid. If any step fails, nothing is kept and the order stays a draft.
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from inventory_apps.erp_pos.exceptions import (
    AccountSetupError, OrderStateError, PaymentError, POSError,
    SessionCloseError, SessionOpenError, SessionStateError, StockUnavailableError,
)


from inventory_core.errors import user_message
class POSService:

    @classmethod
    @transaction.atomic
    def process_payment(cls, pos_order, allow_negative=False):
        """
        Pay a draft order. `allow_negative` is only for offline sales that already
        happened at the counter before they reached the server.
        """
        if pos_order.state != "draft":
            raise OrderStateError("Order is not in draft state")
        if not pos_order.lines.exists():
            raise PaymentError("Add at least one product before paying")

        pos_order.compute_totals()
        if pos_order.amount_paid < pos_order.amount_total:
            raise PaymentError(
                f"Insufficient payment: need {pos_order.amount_total}, got {pos_order.amount_paid}"
            )
        cls._check_payment_methods(pos_order)
        cls._reduce_stock(pos_order, allow_negative)
        cls._post_sale_entry(pos_order)

        pos_order.state = "paid"
        pos_order.save(update_fields=["state"])
        return pos_order

    @classmethod
    def _check_payment_methods(cls, pos_order):
        accepted = set(pos_order.session.config.payment_methods.values_list("pk", flat=True))
        if not accepted:
            return
        for payment in pos_order.payments.all():
            if payment.payment_method_id not in accepted:
                raise PaymentError(
                    f"{payment.payment_method.name} is not accepted on this register."
                )

    @classmethod
    def _reduce_stock(cls, pos_order, allow_negative):
        from inventory_apps.erp_inventory.models import StockMove, StockPicking
        from inventory_apps.erp_inventory.services import StockService

        storable_lines = [l for l in pos_order.lines.all() if l.product.product_type == "storable"]
        if not storable_lines:
            return
        picking_type = StockService.ensure_picking_type("outgoing")
        customer_loc = picking_type.default_location_dest
        src_loc = picking_type.default_location_src
        picking = StockPicking.objects.create(
            picking_type=picking_type,
            partner=pos_order.partner,
            origin=pos_order.name,
            location_src=src_loc,
            location_dest=customer_loc,
            state="confirmed",
        )
        for line in storable_lines:
            StockMove.objects.create(
                picking=picking,
                product=line.product,
                product_uom_qty=line.qty,
                quantity_done=line.qty,
                location_src=src_loc,
                location_dest=customer_loc,
                origin=pos_order.name,
                state="confirmed",
            )
        try:
            StockService.validate_picking(picking, allow_negative=allow_negative)
        except ValueError as e:
            raise StockUnavailableError(user_message(e, "There is not enough stock for this sale."))

    @classmethod
    def _cash_account(cls, method):
        from inventory_apps.erp_accounting.models import AccountAccount

        if method.journal_id and method.journal.default_account_id:
            return method.journal.default_account
        account = AccountAccount.objects.filter(account_type="asset_cash", active=True).first()
        if account is None:
            raise AccountSetupError(
                f"Payment method '{method.name}' has no journal account and no cash account exists."
            )
        return account

    @classmethod
    def _post_sale_entry(cls, pos_order):
        """
        Journal entry for the sale: debit each payment's cash account up to the amount
        due (change is not income), credit revenue for the net amount and tax payable
        for the tax. Cost of goods is posted by the stock delivery itself.
        """
        from inventory_apps.erp_accounting.models import AccountAccount, AccountJournal, AccountMove, AccountMoveLine
        from inventory_apps.erp_accounting.services import AccountingService

        total = pos_order.amount_total
        if total <= Decimal("0.00"):
            return None

        config = pos_order.session.config
        journal = config.journal or AccountJournal.objects.filter(journal_type="sale", active=True).first()
        if journal is None:
            raise AccountSetupError("Set a sales journal on this POS register before taking payment.")

        income = AccountAccount.objects.filter(account_type="income", active=True).first()
        if income is None:
            raise AccountSetupError("No income account is configured for POS sales.")
        tax = pos_order.amount_tax
        tax_account = None
        if tax > Decimal("0.00"):
            tax_account = AccountAccount.objects.filter(
                account_type="liability_current", is_tax_account=True, active=True,
            ).first()
            if tax_account is None:
                raise AccountSetupError(
                    "Tax was charged but no tax account is set up. Flag an account as a tax account."
                )

        move = AccountMove.objects.create(
            move_type="entry",
            journal=journal,
            ref=pos_order.name,
            narration=f"POS sale {pos_order.name}",
            date=timezone.localdate(),
        )
        remaining = total
        for payment in pos_order.payments.select_related("payment_method__journal").all():
            take = min(payment.amount, remaining)
            if take <= Decimal("0.00"):
                continue
            AccountMoveLine.objects.create(
                move=move,
                account=cls._cash_account(payment.payment_method),
                name=f"{pos_order.name} {payment.payment_method.name}",
                debit=take,
                credit=Decimal("0.00"),
            )
            remaining -= take

        AccountMoveLine.objects.create(
            move=move, account=income, name=f"POS sale {pos_order.name}",
            debit=Decimal("0.00"), credit=total - tax,
        )
        if tax_account is not None:
            AccountMoveLine.objects.create(
                move=move, account=tax_account, name="Tax",
                debit=Decimal("0.00"), credit=tax,
            )
        AccountingService.post_move(move)
        return move

    @classmethod
    def _build_offline_order(cls, session, data, ref):
        """Create a draft order and its lines and payments from one offline sale."""
        from inventory_apps.erp_base.models import ProductVariant
        from inventory_apps.erp_pos.models import POSOrder, POSOrderLine, POSPayment, POSPaymentMethod

        try:
            order = POSOrder.objects.create(
                session=session,
                partner_id=data.get("partner_id"),
                date_order=data.get("date_order") or timezone.now(),
                note=data.get("note", ""),
                external_ref=ref,
            )
            for line_data in data.get("lines", []):
                product = ProductVariant.objects.get(pk=line_data["product_id"])
                price = line_data.get("price_unit")
                POSOrderLine.objects.create(
                    order=order,
                    product=product,
                    qty=Decimal(str(line_data.get("qty", 1))),
                    price_unit=Decimal(str(price)) if price is not None else product.product_template.sale_price,
                    discount=Decimal(str(line_data.get("discount", 0))),
                )
            for pay_data in data.get("payments", []):
                method = POSPaymentMethod.objects.get(pk=pay_data["method_id"])
                POSPayment.objects.create(
                    pos_order=order,
                    payment_method=method,
                    amount=Decimal(str(pay_data["amount"])),
                    session=session,
                )
        except (KeyError, ValueError, InvalidOperation) as e:
            raise PaymentError(f"Offline sale {ref or '(no reference)'} could not be processed: {user_message(e, 'its details are incomplete')}")
        except ObjectDoesNotExist as e:
            raise PaymentError(f"Offline sale {ref or '(no reference)'} could not be processed: {user_message(e, 'its details no longer match this business')}")
        order.compute_totals()
        return order

    @classmethod
    def sync_offline_orders(cls, session, orders_data: list) -> dict:
        """
        Sync sales recorded while the register was offline. Each sale is handled in its
        own savepoint: one bad sale is reported and the rest still go through. A sale
        already synced (same external reference) is skipped, so retrying is safe.
        """
        from inventory_apps.erp_pos.models import POSOrder

        result = {"created": [], "skipped": [], "failed": []}
        for data in orders_data:
            ref = str(data.get("external_ref") or data.get("id") or "")
            if ref and POSOrder.objects.filter(session=session, external_ref=ref).exists():
                result["skipped"].append(ref)
                continue
            try:
                with transaction.atomic():
                    order = cls._build_offline_order(session, data, ref)
                    cls.process_payment(order, allow_negative=True)
                result["created"].append(str(order.id))
            except POSError as e:
                result["failed"].append({"external_ref": ref, "error": str(e.detail)})
        return result

    @classmethod
    @transaction.atomic
    def open_session(cls, config, opening_balance: Decimal, opening_notes: str = ""):
        """Open a register. The config row is locked so two requests cannot both open one."""
        from inventory_apps.erp_pos.models import POSConfig, POSSession

        locked = POSConfig.objects.select_for_update().get(pk=config.pk)
        if POSSession.objects.filter(config=locked, state="opened").exists():
            raise SessionOpenError()
        session = POSSession.objects.create(config=locked)
        session.open_session(opening_balance, opening_notes)
        return session

    @classmethod
    @transaction.atomic
    def close_session(cls, session, closing_balance: Decimal = Decimal("0.00"), notes: str = ""):
        """Close an open register. Refused while any order is still an unpaid draft."""
        if session.state != "opened":
            raise SessionStateError("Only open sessions can be closed")
        if session.orders.filter(state="draft").exists():
            raise SessionCloseError()
        session.close_session(closing_balance, notes)
        return session

    @classmethod
    def get_session_summary(cls, session):
        from inventory_apps.erp_pos.models import POSPayment
        from django.db.models import Sum

        orders = session.orders.filter(state__in=["paid", "done", "invoiced"])
        payments_by_method = (
            POSPayment.objects.filter(pos_order__session=session)
            .values("payment_method__name")
            .annotate(total=Sum("amount"))
        )

        return {
            "session_id": str(session.id),
            "session_name": session.name,
            "state": session.state,
            "opened_at": session.opened_at,
            "closed_at": session.closed_at,
            "order_count": orders.count(),
            "total_sales": orders.aggregate(t=Sum("amount_total"))["t"] or Decimal("0.00"),
            "cash_in": session.cash_register_balance_start,
            "cash_out": session.cash_register_balance_end,
            "cash_diff": session.cash_register_difference,
            "payments_by_method": list(payments_by_method),
        }
