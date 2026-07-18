from rest_framework import serializers
from inventory_apps.erp_accounting.models import (
    AccountAccount, AccountJournal, AccountMove, AccountMoveLine, AccountPayment,
)


class AccountAccountSerializer(serializers.ModelSerializer):
    currency_code = serializers.CharField(source="currency.code", read_only=True, default="")
    account_type_display = serializers.CharField(source="get_account_type_display", read_only=True)

    class Meta:
        model = AccountAccount
        fields = [
            "id", "code", "name", "account_type", "account_type_display", "group",
            "currency", "currency_code", "reconcile", "deprecated", "active", "note",
        ]


class AccountJournalSerializer(serializers.ModelSerializer):
    journal_type_display = serializers.CharField(source="get_journal_type_display", read_only=True)
    currency_code = serializers.CharField(source="currency.code", read_only=True, default="")
    default_account_name = serializers.SerializerMethodField()

    class Meta:
        model = AccountJournal
        fields = [
            "id", "name", "code", "journal_type", "journal_type_display",
            "company", "currency", "currency_code",
            "default_account", "default_account_name",
            "suspense_account", "sequence_prefix", "active",
        ]

    def get_default_account_name(self, obj):
        if obj.default_account_id:
            return f"{obj.default_account.code} {obj.default_account.name}"
        return ""


class AccountMoveLineSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)
    account_code = serializers.CharField(source="account.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = AccountMoveLine
        fields = [
            "id", "sequence",
            "account", "account_code", "account_name",
            "partner", "name",
            "product", "product_name",
            "quantity", "price_unit", "discount",
            "price_subtotal", "tax_amount", "price_total",
            "debit", "credit", "balance",
            "amount_residual", "reconciled",
            "exclude_from_invoice_tab",
            "date_maturity",
        ]
        read_only_fields = ["price_subtotal", "tax_amount", "price_total", "balance"]


class AccountMoveSerializer(serializers.ModelSerializer):
    lines = AccountMoveLineSerializer(many=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    journal_name = serializers.CharField(source="journal.name", read_only=True)
    move_type_display = serializers.CharField(source="get_move_type_display", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)

    class Meta:
        model = AccountMove
        fields = [
            "id", "name", "ref",
            "move_type", "move_type_display",
            "state", "state_display", "payment_state",
            "journal", "journal_name",
            "partner", "partner_name",
            "currency", "date", "invoice_date", "invoice_date_due",
            "invoice_origin", "narration",
            "amount_untaxed", "amount_tax", "amount_total",
            "amount_residual", "amount_paid",
            "sale_order", "purchase_order",
            "lines", "created_at", "updated_at",
        ]
        read_only_fields = [
            "name", "state", "payment_state",
            "amount_untaxed", "amount_tax", "amount_total",
            "amount_residual", "amount_paid",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        move = AccountMove.objects.create(**validated_data)
        for line_data in lines_data:
            AccountMoveLine.objects.create(move=move, **line_data)
        move.compute_totals()
        return move

    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)
        if instance.state == "posted":
            raise serializers.ValidationError("Cannot edit a posted journal entry")
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                AccountMoveLine.objects.create(move=instance, **line_data)
            instance.compute_totals()
        return instance


class AccountMoveListSerializer(serializers.ModelSerializer):
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    move_type_display = serializers.CharField(source="get_move_type_display", read_only=True)

    class Meta:
        model = AccountMove
        fields = [
            "id", "name", "move_type", "move_type_display",
            "state", "payment_state",
            "partner_name", "date", "invoice_date", "invoice_date_due",
            "invoice_origin",
            "amount_untaxed", "amount_total", "amount_residual",
        ]


class AccountPaymentSerializer(serializers.ModelSerializer):
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    journal_name = serializers.CharField(source="journal.name", read_only=True)

    class Meta:
        model = AccountPayment
        fields = [
            "id", "name", "payment_type", "partner_type",
            "partner", "partner_name",
            "journal", "journal_name", "currency",
            "amount", "date", "memo", "state",
            "reconcile_move", "created_at",
        ]
        read_only_fields = ["name", "state"]


class TrialBalanceRowSerializer(serializers.Serializer):
    account_code = serializers.CharField(source="account__code")
    account_name = serializers.CharField(source="account__name")
    account_type = serializers.CharField(source="account__account_type")
    total_debit = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_credit = serializers.DecimalField(max_digits=18, decimal_places=2)


class RegisterPaymentSerializer(serializers.Serializer):
    journal = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    date = serializers.DateField(required=False)
    memo = serializers.CharField(required=False, default="")
