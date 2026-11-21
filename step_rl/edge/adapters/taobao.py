"""Taobao/Tmall read-only adapter (AR030)."""

from __future__ import annotations

from .remote import RemoteReadOnlyAdapter


class TaobaoAdapter(RemoteReadOnlyAdapter):
    name = "taobao"

    def __init__(self, **kwargs):
        super().__init__(
            site_name="taobao",
            search_template="https://s.taobao.com/search?q={query}",
            login_hosts=("login.taobao.com", "passport.taobao.com"),
            item_hosts=(
                "item.taobao.com",
                "detail.tmall.com",
                "chaoshi.detail.tmall.com",
            ),
            **kwargs,
        )
