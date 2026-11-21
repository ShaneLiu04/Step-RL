"""Adapter registry (AR033): site names -> concrete adapters."""

from __future__ import annotations

from typing import Any

from .amazon import AmazonAdapter
from .jd import JDAdapter
from .taobao import TaobaoAdapter

_FACTORIES = {
    "jd": JDAdapter,
    "taobao": TaobaoAdapter,
    "amazon": AmazonAdapter,
}


def create_adapter(site: str, **kwargs: Any):
    factory = _FACTORIES.get(site)
    if factory is None:
        raise ValueError(f"unsupported site: {site}")
    return factory(**kwargs)
