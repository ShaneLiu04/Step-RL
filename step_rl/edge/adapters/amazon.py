"""Amazon read-only adapter (AR030)."""

from __future__ import annotations

from .remote import RemoteReadOnlyAdapter


class AmazonAdapter(RemoteReadOnlyAdapter):
    name = "amazon"

    def __init__(self, **kwargs):
        super().__init__(
            site_name="amazon",
            search_template="https://www.amazon.com/s?k={query}",
            login_hosts=("signin.aws.amazon.com", "www.amazon.com/ap/signin"),
            item_hosts=("www.amazon.com/dp/", "www.amazon.com/gp/product/"),
            **kwargs,
        )
