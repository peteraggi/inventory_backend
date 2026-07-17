from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from decimal import Decimal

from inventory_apps.erp_pos.models import (
    POSConfig, POSPaymentMethod, POSSession, POSOrder, POSOrderLine, POSPayment,
)
from inventory_apps.erp_pos.serializers import (
    POSConfigSerializer, POSPaymentMethodSerializer,
    POSSessionSerializer, POSOrderSerializer, POSOrderListSerializer,
    POSPaymentSerializer, OfflineSyncSerializer,
)
from inventory_apps.erp_pos.services import POSService


class POSPaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = POSPaymentMethod.objects.filter(active=True)
    serializer_class = POSPaymentMethodSerializer
    permission_classes = [IsAuthenticated]


class POSConfigViewSet(viewsets.ModelViewSet):
    queryset = POSConfig.objects.filter(active=True).prefetch_related("payment_methods")
    serializer_class = POSConfigSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"], url_path="open-session")
    def open_session(self, request, pk=None):
        config = self.get_object()
        if config.current_session:
            return Response(
                {"error": "There is already an open session for this POS"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        opening_balance = Decimal(str(request.data.get("opening_balance", "0")))
        session = POSSession.objects.create(config=config)
        session.open_session(opening_balance)
        return Response(POSSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class POSSessionViewSet(viewsets.ModelViewSet):
    queryset = POSSession.objects.all().select_related("config")
    serializer_class = POSSessionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["state", "config"]

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        session = self.get_object()
        if session.state != "opened":
            return Response(
                {"error": "Only open sessions can be closed"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        closing_balance = Decimal(str(request.data.get("closing_balance", "0")))
        notes = request.data.get("notes", "")
        POSService.close_session(session, closing_balance, notes)
        return Response(POSSessionSerializer(session).data)

    @action(detail=True, url_path="summary")
    def summary(self, request, pk=None):
        session = self.get_object()
        return Response(POSService.get_session_summary(session))

    @action(detail=True, methods=["post"], url_path="sync-offline")
    def sync_offline(self, request, pk=None):
        session = self.get_object()
        ser = OfflineSyncSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        orders_data = ser.validated_data["orders"]
        try:
            created_ids = POSService.sync_offline_orders(session, orders_data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"synced": len(created_ids), "order_ids": created_ids})


class POSOrderViewSet(viewsets.ModelViewSet):
    queryset = POSOrder.objects.all().select_related(
        "session", "partner"
    ).prefetch_related("lines__product", "payments__payment_method")
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name"]
    filterset_fields = ["state", "session"]

    def get_serializer_class(self):
        if self.action == "list":
            return POSOrderListSerializer
        return POSOrderSerializer

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        order = self.get_object()
        try:
            POSService.process_payment(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(POSOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.state in ("paid", "done", "invoiced"):
            return Response(
                {"error": "Cannot cancel a paid order"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.state = "cancel"
        order.save(update_fields=["state"])
        return Response(POSOrderSerializer(order).data)

    @action(detail=True, url_path="payments")
    def payments(self, request, pk=None):
        order = self.get_object()
        return Response(POSPaymentSerializer(order.payments.all(), many=True).data)
