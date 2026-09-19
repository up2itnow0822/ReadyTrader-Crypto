from __future__ import annotations

import asyncio
import inspect

from tools.generate_tool_docs import _load_tools


def test_public_tool_registry_preserves_callable_metadata() -> None:
    tools = asyncio.run(_load_tools())

    assert len(tools) == 29
    tool = tools["place_cex_order"]
    signature = inspect.signature(tool.fn)

    assert list(signature.parameters) == [
        "symbol",
        "side",
        "amount",
        "order_type",
        "price",
        "exchange",
        "market_type",
        "idempotency_key",
    ]
    assert signature.parameters["symbol"].annotation == "str"
    assert signature.parameters["side"].annotation == "str"
    assert signature.parameters["amount"].annotation == "float"
    assert signature.parameters["order_type"].default == "market"
    assert signature.parameters["price"].default is None
    assert signature.parameters["exchange"].default == "binance"
    assert signature.parameters["market_type"].default == "spot"
    assert signature.parameters["idempotency_key"].default == ""
    assert tool.parameters["required"] == ["symbol", "side", "amount"]
    assert tool.description.startswith("Place an order on a CEX")
