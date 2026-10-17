from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Page-number pagination with a client-adjustable, bounded page size."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
