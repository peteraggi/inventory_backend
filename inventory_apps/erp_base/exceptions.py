# inventory_apps/erp_base/exceptions.py

from rest_framework import status
from rest_framework.exceptions import APIException


class ContactInUseError(APIException):
    """A customer or vendor with orders, bills or payments cannot be deleted."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'This contact has orders, bills or payments and cannot be deleted.'
    default_code = 'contact_in_use'
