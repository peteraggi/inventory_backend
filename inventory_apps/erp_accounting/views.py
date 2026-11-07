from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound, PermissionDenied

from inventory_apps.authentication.permissions import HasErpPermission
from django_filters.rest_framework import DjangoFilterBackend
from inventory_core.exceptions import inventory_exception_handler

from inventory_apps.erp_accounting.dashboard import DashboardService
from inventory_apps.erp_accounting.exceptions import PostedDocumentError
from inventory_apps.erp_accounting.models import (
    AccountAccount, AccountJournal, AccountMove, AccountPayment,
)
from inventory_apps.erp_accounting.serializers import (
    AccountAccountSerializer, AccountJournalSerializer,
    AccountMoveSerializer, AccountMoveListSerializer,
    AccountPaymentSerializer, RegisterPaymentSerializer,
)
from inventory_apps.erp_accounting.services import AccountingService


class AccountingErrorMixin:
    """Every accounting endpoint returns {"success": False, "error": "..."} on failure."""

    def get_exception_handler(self):
        return inventory_exception_handler


class AccountAccountViewSet(AccountingErrorMixin, viewsets.ModelViewSet):
    """Chart of accounts. Every posting uses these accounts, so changes apply immediately."""
    queryset = AccountAccount.objects.filter(active=True, deprecated=False).order_by("code")
    serializer_class = AccountAccountSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "accounting"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["code", "name"]
    filterset_fields = ["account_type", "reconcile"]


class AccountJournalViewSet(AccountingErrorMixin, viewsets.ModelViewSet):
    """Journals grouped by purpose: sales, purchase, cash, bank, miscellaneous."""
    queryset = AccountJournal.objects.filter(active=True).select_related("default_account", "currency")
    serializer_class = AccountJournalSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "accounting"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "code"]
    filterset_fields = ["journal_type"]


class AccountMoveViewSet(AccountingErrorMixin, viewsets.ModelViewSet):
    """
    Journal entries, invoices, bills and credit notes.

    Drafts can be edited. Posting makes a document part of the ledger; a posted
    document is read-only and is corrected with a reversing entry.
    """
    queryset = AccountMove.objects.all().select_related(
        "journal", "partner", "currency"
    ).prefetch_related("lines__account", "lines__product")
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "accounting"
    erp_action_map = {
        "post": "update",
        "recompute_journal_items": "update",
        "register_payment": "update",
        "cancel": "update",
    }
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name", "ref", "invoice_origin"]
    filterset_fields = ["move_type", "state", "payment_state", "partner", "invoice_origin"]

    def get_serializer_class(self):
        if self.action == "list":
            return AccountMoveListSerializer
        return AccountMoveSerializer

    def perform_destroy(self, instance):
        if instance.state == "posted":
            raise PostedDocumentError()
        instance.delete()

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        """Post the document to the ledger. Refused if it has no lines or accounts are not set up."""
        move = self.get_object()
        AccountingService.post_move(move)
        return Response(AccountMoveSerializer(move).data)

    @action(detail=True, methods=["post"], url_path="recompute-journal-items")
    def recompute_journal_items(self, request, pk=None):
        """Rebuild the generated journal lines of a posted invoice or bill."""
        move = self.get_object()
        AccountingService.recompute_journal_items(move)
        return Response(AccountMoveSerializer(move).data)

    @action(detail=True, methods=["post"], url_path="register-payment")
    def register_payment(self, request, pk=None):
        """Record a payment against a posted invoice or bill, up to the amount still due."""
        move = self.get_object()
        ser = RegisterPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            journal = AccountJournal.objects.get(pk=data["journal"])
        except AccountJournal.DoesNotExist:
            raise NotFound("Journal not found")
        payment = AccountingService.register_payment(
            move, data["amount"], journal,
            data.get("date"), data.get("memo", ""),
        )
        return Response(AccountPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a draft. A posted document cannot be cancelled; reverse it instead."""
        move = self.get_object()
        if move.state == "posted":
            raise PostedDocumentError("Cannot cancel a posted entry. Please use a reversal.")
        move.state = "cancel"
        move.save(update_fields=["state"])
        return Response(AccountMoveSerializer(move).data)


class AccountPaymentViewSet(AccountingErrorMixin, viewsets.ModelViewSet):
    """Payments. A payment is locked once posted."""
    queryset = AccountPayment.objects.all().select_related("partner", "journal", "currency")
    serializer_class = AccountPaymentSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "accounting"
    erp_action_map = {"post": "update"}
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["state", "payment_type", "partner_type", "partner"]
    search_fields = ["name", "memo", "partner__name"]

    def perform_update(self, serializer):
        # Anything past draft (posted or reconciled against an invoice) is part of the ledger.
        if serializer.instance.state != "draft":
            raise PostedDocumentError("A posted payment cannot be changed.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.state != "draft":
            raise PostedDocumentError("A posted payment cannot be deleted.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        """Post a draft payment and give it its reference number."""
        payment = self.get_object()
        AccountingService.post_payment(payment)
        return Response(AccountPaymentSerializer(payment).data)


class ReportViewSet(AccountingErrorMixin, viewsets.ViewSet):
    """Read-only financial reports and dashboard figures."""
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "reports"

    def get_permissions(self):
        # The dashboard shows whichever figures the user can see; the action checks that itself.
        if self.action == "dashboard_summary":
            return [IsAuthenticated()]
        return super().get_permissions()

    @action(detail=False, url_path="trial-balance")
    def trial_balance(self, request):
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        rows = list(AccountingService.get_trial_balance(date_from, date_to))
        from decimal import Decimal
        total_debit = sum(r["total_debit"] or Decimal("0") for r in rows)
        total_credit = sum(r["total_credit"] or Decimal("0") for r in rows)
        return Response({
            "rows": rows,
            "total_debit": total_debit,
            "total_credit": total_credit,
        })

    @action(detail=False, url_path="profit-and-loss")
    def profit_and_loss(self, request):
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        return Response(AccountingService.get_profit_and_loss(date_from, date_to))

    @action(detail=False, url_path="aged-receivable")
    def aged_receivable(self, request):
        from inventory_apps.erp_accounting.models import AccountMove
        from django.utils import timezone
        today = timezone.now().date()
        invoices = AccountMove.objects.filter(
            move_type="out_invoice",
            state="posted",
        ).exclude(payment_state="paid").select_related("partner")
        rows = []
        for inv in invoices:
            days = (today - inv.invoice_date_due).days if inv.invoice_date_due else 0
            rows.append({
                "id": str(inv.id),
                "name": inv.name,
                "partner": inv.partner.name if inv.partner else "",
                "invoice_date": inv.invoice_date,
                "due_date": inv.invoice_date_due,
                "amount_total": inv.amount_total,
                "amount_residual": inv.amount_residual,
                "days_overdue": max(days, 0),
            })
        rows.sort(key=lambda r: r["days_overdue"], reverse=True)
        return Response(rows)

    @action(detail=False, url_path="dashboard-summary")
    def dashboard_summary(self, request):
        """Headline sales, order counts, low stock and chart data for the dashboard."""
        from inventory_apps.authentication.rbac import user_can
        if not any(user_can(request.user, module, "read") for module in ("sales", "pos", "inventory")):
            raise PermissionDenied("You need access to sales, point of sale or inventory to see the dashboard.")
        return Response(DashboardService.summary())

    @action(detail=False, url_path="aged-payable")
    def aged_payable(self, request):
        from inventory_apps.erp_accounting.models import AccountMove
        from django.utils import timezone
        today = timezone.now().date()
        bills = AccountMove.objects.filter(
            move_type="in_invoice",
            state="posted",
        ).exclude(payment_state="paid").select_related("partner")
        rows = []
        for bill in bills:
            days = (today - bill.invoice_date_due).days if bill.invoice_date_due else 0
            rows.append({
                "id": str(bill.id),
                "name": bill.name,
                "partner": bill.partner.name if bill.partner else "",
                "invoice_date": bill.invoice_date,
                "due_date": bill.invoice_date_due,
                "amount_total": bill.amount_total,
                "amount_residual": bill.amount_residual,
                "days_overdue": max(days, 0),
            })
        rows.sort(key=lambda r: r["days_overdue"], reverse=True)
        return Response(rows)
