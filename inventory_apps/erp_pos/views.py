# inventory_apps/erp_pos/views.py

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from inventory_apps.authentication.permissions import HasErpPermission
from inventory_apps.erp_pos.exceptions import OrderStateError
from inventory_apps.erp_pos.models import (
    POSConfig, POSPaymentMethod, POSSession, POSOrder,
)
from inventory_apps.erp_pos.serializers import (
    POSConfigSerializer, POSPaymentMethodSerializer,
    POSSessionSerializer, POSOrderSerializer, POSOrderListSerializer,
    POSPaymentSerializer, OfflineSyncSerializer,
)
from inventory_apps.erp_pos.services import POSService
from inventory_core.exceptions import inventory_exception_handler


class POSErrorMixin:
    """Every POS endpoint returns {"success": False, "error": "..."} on failure."""

    def get_exception_handler(self):
        return inventory_exception_handler


def _decimal(value, default="0"):
    try:
        return Decimal(str(value if value is not None else default))
    except InvalidOperation:
        raise ValidationError({"amount": f"'{value}' is not a valid number."})


class POSPaymentMethodViewSet(POSErrorMixin, viewsets.ModelViewSet):
    """Payment methods a register can accept (cash, card, transfer...)."""
    queryset = POSPaymentMethod.objects.filter(active=True)
    serializer_class = POSPaymentMethodSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "pos"


class POSConfigViewSet(POSErrorMixin, viewsets.ModelViewSet):
    """Registers. A register opens and closes sessions; each session takes the sales."""
    queryset = POSConfig.objects.filter(active=True).prefetch_related("payment_methods")
    serializer_class = POSConfigSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "pos"
    erp_action_map = {"open_session": "update"}

    @action(detail=True, methods=["post"], url_path="open-session")
    def open_session(self, request, pk=None):
        """Open a new session on this register. Only one session can be open at a time."""
        config = self.get_object()
        session = POSService.open_session(
            config,
            _decimal(request.data.get("opening_balance")),
            request.data.get("opening_notes", ""),
        )
        return Response(POSSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class POSSessionViewSet(POSErrorMixin, viewsets.ReadOnlyModelViewSet):
    """
    Register sessions. Records are read-only; a session changes only through
    close, sync-offline and the register's open-session action.
    """
    queryset = POSSession.objects.all().select_related("config")
    serializer_class = POSSessionSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "pos"
    erp_action_map = {"close": "update", "sync_offline": "update"}
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["state", "config"]

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        """Close an open session. Refused while any order is still an unpaid draft."""
        session = self.get_object()
        POSService.close_session(
            session,
            _decimal(request.data.get("closing_balance")),
            request.data.get("notes", ""),
        )
        return Response(POSSessionSerializer(session).data)

    @action(detail=True, url_path="summary")
    def summary(self, request, pk=None):
        """Sales, payments by method and cash figures for the session."""
        session = self.get_object()
        return Response(POSService.get_session_summary(session))

    @action(detail=True, methods=["post"], url_path="sync-offline")
    def sync_offline(self, request, pk=None):
        """
        Upload sales recorded offline. Returns what was created, what was already synced
        (skipped) and what failed, with the reason for each failure.
        """
        session = self.get_object()
        ser = OfflineSyncSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if session.state != "opened":
            raise OrderStateError("Offline sales can only be synced into an open session.")
        result = POSService.sync_offline_orders(session, ser.validated_data["orders"])
        return Response({
            "synced": len(result["created"]),
            "order_ids": result["created"],
            "skipped": result["skipped"],
            "failed": result["failed"],
        })


class POSOrderViewSet(POSErrorMixin, viewsets.ModelViewSet):
    """
    Counter sales. A sale is a draft until it is paid: lines and payments can change,
    then pay reduces stock, posts the sale to the ledger and locks the order.
    """
    queryset = POSOrder.objects.all().select_related(
        "session", "partner"
    ).prefetch_related("lines__product", "payments__payment_method")
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "pos"
    erp_action_map = {"pay": "update", "cancel": "update"}
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name", "external_ref"]
    filterset_fields = ["state", "session"]

    def get_serializer_class(self):
        if self.action == "list":
            return POSOrderListSerializer
        return POSOrderSerializer

    def perform_destroy(self, instance):
        if instance.state != "draft":
            raise OrderStateError("Only a new order can be deleted.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Finalize a draft sale: stock, ledger and the paid state change together or not at all."""
        order = self.get_object()
        with transaction.atomic():
            POSService.process_payment(order)
        return Response(POSOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a draft sale. A paid sale cannot be cancelled."""
        order = self.get_object()
        if order.state != "draft":
            raise OrderStateError("Cannot cancel a paid order.")
        order.state = "cancel"
        order.save(update_fields=["state"])
        return Response(POSOrderSerializer(order).data)

    @action(detail=True, url_path="payments")
    def payments(self, request, pk=None):
        """Payments recorded on this sale."""
        order = self.get_object()
        return Response(POSPaymentSerializer(order.payments.all(), many=True).data)
