# inventory_apps/erp_sales/exceptions.py

from rest_framework import status
from rest_framework.exceptions import APIException


class SalesOrderError(APIException):
    """Base for sales order failures. The message is returned to the client as `error`."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Sales order could not be processed.'
    default_code = 'sales_order_error'


class OrderStateError(SalesOrderError):
    """The action is not allowed for the order's current state."""
    default_detail = 'This action is not allowed for the order in its current state.'
    default_code = 'order_state_error'


class OrderLockedError(SalesOrderError):
    """Lines are fixed once the order has been confirmed."""
    default_detail = 'Lines can only be changed while the order is a quotation.'
    default_code = 'order_locked'


class OrderCancellationError(SalesOrderError):
    """Goods have left or the order is invoiced, so it can no longer be cancelled."""
    default_detail = 'This order can no longer be cancelled.'
    default_code = 'cancellation_refused'


class AlreadyInvoicedError(SalesOrderError):
    """Every line has already been invoiced."""
    default_detail = 'Everything on this order is already invoiced'
    default_code = 'already_invoiced'


class AccountingSetupError(SalesOrderError):
    """Journals or accounts needed for invoicing are missing."""
    default_detail = 'Accounting is not set up for invoicing.'
    default_code = 'accounting_not_configured'
