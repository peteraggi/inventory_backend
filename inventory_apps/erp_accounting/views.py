from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from inventory_apps.erp_accounting.models import (
    AccountAccount, AccountJournal, AccountMove, AccountMoveLine, AccountPayment,
)
from inventory_apps.erp_accounting.serializers import (
    AccountAccountSerializer, AccountJournalSerializer,
    AccountMoveSerializer, AccountMoveListSerializer, AccountMoveLineSerializer,
    AccountPaymentSerializer, RegisterPaymentSerializer, TrialBalanceRowSerializer,
)
from inventory_apps.erp_accounting.services import AccountingService


class AccountAccountViewSet(viewsets.ModelViewSet):
    queryset = AccountAccount.objects.filter(active=True, deprecated=False).order_by("code")
    serializer_class = AccountAccountSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["code", "name"]
    filterset_fields = ["account_type", "reconcile"]


class AccountJournalViewSet(viewsets.ModelViewSet):
    queryset = AccountJournal.objects.filter(active=True).select_related("default_account", "currency")
    serializer_class = AccountJournalSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "code"]
    filterset_fields = ["journal_type"]


class AccountMoveViewSet(viewsets.ModelViewSet):
    queryset = AccountMove.objects.all().select_related(
        "journal", "partner", "currency"
    ).prefetch_related("lines__account", "lines__product")
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name", "ref", "invoice_origin"]
    filterset_fields = ["move_type", "state", "payment_state", "partner", "invoice_origin"]

    def get_serializer_class(self):
        if self.action == "list":
            return AccountMoveListSerializer
        return AccountMoveSerializer

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        move = self.get_object()
        try:
            AccountingService.post_move(move)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AccountMoveSerializer(move).data)

    @action(detail=True, methods=["post"], url_path="register-payment")
    def register_payment(self, request, pk=None):
        move = self.get_object()
        ser = RegisterPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            journal = AccountJournal.objects.get(pk=data["journal"])
        except AccountJournal.DoesNotExist:
            return Response({"error": "Journal not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            payment = AccountingService.register_payment(
                move, data["amount"], journal,
                data.get("date"), data.get("memo", ""),
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AccountPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        move = self.get_object()
        if move.state == "posted":
            return Response(
                {"error": "Cannot cancel a posted entry. Please use a reversal."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        move.state = "cancel"
        move.save(update_fields=["state"])
        return Response(AccountMoveSerializer(move).data)


class AccountPaymentViewSet(viewsets.ModelViewSet):
    queryset = AccountPayment.objects.all().select_related("partner", "journal", "currency")
    serializer_class = AccountPaymentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["state", "payment_type", "partner_type", "partner"]
    search_fields = ["name", "memo", "partner__name"]

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        payment = self.get_object()
        try:
            AccountingService.post_payment(payment)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AccountPaymentSerializer(payment).data)


class ReportViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

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
