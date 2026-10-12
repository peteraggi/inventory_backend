from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Default list pagination: 10 per page, overridable per request with
    `?page_size=` (used by the dashboard's paged tables)."""
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 200
