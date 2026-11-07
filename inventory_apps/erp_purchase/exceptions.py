# inventory_apps/erp_purchase/exceptions.py

from rest_framework import status
from rest_framework.exceptions import APIException


class PurchaseOrderError(APIException):
    """Base for purchase order failures. The message is returned to the client as `error`."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Purchase order could not be processed.'
    default_code = 'purchase_order_error'


class OrderStateError(PurchaseOrderError):
    """The action is not allowed for the order's current state."""
    default_detail = 'This action is not allowed for the order in its current state.'
    default_code = 'order_state_error'


class OrderLockedError(PurchaseOrderError):
    """Lines are fixed once the order has been confirmed."""
    default_detail = 'Lines can only be changed while the RFQ is not yet confirmed.'
    default_code = 'order_locked'


class OrderCancellationError(PurchaseOrderError):
    """Goods have arrived or the order is billed, so it can no longer be cancelled."""
    default_detail = 'This order can no longer be cancelled.'
    default_code = 'cancellation_refused'


class AlreadyBilledError(PurchaseOrderError):
    """Every line has already been billed."""
    default_detail = 'Everything on this order is already billed'
    default_code = 'already_billed'


class AccountingSetupError(PurchaseOrderError):
    """Journals or accounts needed for vendor bills are missing."""
    default_detail = 'Accounting is not set up for vendor bills.'
    default_code = 'accounting_not_configured'
