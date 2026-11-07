# inventory_apps/erp_pos/exceptions.py

from rest_framework import status
from rest_framework.exceptions import APIException


class POSError(APIException):
    """Base for point-of-sale failures. The message is returned to the client as `error`."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Point of sale request could not be processed.'
    default_code = 'pos_error'


class OrderStateError(POSError):
    """The order is not in a state that allows this action."""
    default_detail = 'This action is not allowed for the order in its current state.'
    default_code = 'order_state_error'


class SessionStateError(POSError):
    """The session is not in a state that allows this action."""
    default_detail = 'This action is not allowed for the session in its current state.'
    default_code = 'session_state_error'


class SessionOpenError(POSError):
    """The register already has an open session."""
    default_detail = 'There is already an open session for this POS.'
    default_code = 'session_already_open'


class SessionCloseError(POSError):
    """The session still has unfinished orders."""
    default_detail = 'Close is blocked: this session still has unpaid orders.'
    default_code = 'session_has_drafts'


class PaymentError(POSError):
    """The payment does not cover the order, or uses a method the register does not accept."""
    default_detail = 'Payment could not be processed.'
    default_code = 'payment_error'


class StockUnavailableError(POSError):
    """Not enough stock is on hand for a sale made online."""
    default_detail = 'Not enough stock to complete this sale.'
    default_code = 'stock_unavailable'


class AccountSetupError(POSError):
    """Journals or accounts needed to post the sale are missing."""
    default_detail = 'Accounting is not set up for point of sale.'
    default_code = 'account_setup'
