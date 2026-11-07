# inventory_apps/erp_accounting/exceptions.py

from rest_framework import status
from rest_framework.exceptions import APIException


class AccountingError(APIException):
    """Base for accounting failures. The message is returned to the client as `error`."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Accounting request could not be processed.'
    default_code = 'accounting_error'


class PostedDocumentError(AccountingError):
    """Posted entries and payments are part of the ledger and cannot be changed or deleted."""
    default_detail = 'Posted documents cannot be changed. Create a reversing entry instead.'
    default_code = 'posted_document'


class AccountSetupError(AccountingError):
    """A required account or journal is missing, so the entry cannot be built correctly."""
    default_detail = 'Accounting is not set up for this document.'
    default_code = 'account_setup'


class EmptyDocumentError(AccountingError):
    """An invoice, bill or entry must have lines before it can be posted."""
    default_detail = 'Add at least one line before posting.'
    default_code = 'empty_document'


class UnbalancedEntryError(AccountingError):
    """Debits and credits do not match."""
    default_detail = 'Journal entry does not balance.'
    default_code = 'unbalanced_entry'


class PaymentError(AccountingError):
    """A payment amount or document state does not allow the payment."""
    default_detail = 'Payment could not be registered.'
    default_code = 'payment_error'


class InvalidStateError(AccountingError):
    """The action is not allowed for the document's current state."""
    default_detail = 'This action is not allowed in the current state.'
    default_code = 'invalid_state'
