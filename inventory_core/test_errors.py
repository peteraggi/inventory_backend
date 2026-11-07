# inventory_core/test_errors.py
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from inventory_core.errors import user_message


class UserMessageTests(SimpleTestCase):

    def test_drf_validation_detail_is_passed_through(self):
        self.assertEqual(user_message(ValidationError("Pick a location."), "x"), "Pick a location.")

    def test_django_validation_dict_is_flattened_to_its_message(self):
        error = DjangoValidationError({"store": ["Regular users must be assigned to a store."]})

        self.assertEqual(user_message(error, "fallback"), "Regular users must be assigned to a store.")

    def test_deliberate_value_errors_keep_their_wording(self):
        self.assertEqual(user_message(ValueError("Quantity must be positive."), "x"), "Quantity must be positive.")

    def test_database_and_library_text_is_replaced_by_the_fallback(self):
        error = RuntimeError('duplicate key value violates unique constraint "pos_app_store_code_key"')

        self.assertEqual(user_message(error, "Could not save."), "Could not save.")
