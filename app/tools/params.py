"""Types for MCP tool parameters.

FastMCP validates tool arguments with pydantic in lax mode, which turns JSON true/false into 1/0 (or
1.0/0.0) for a numeric parameter before the tool runs: an order for `true` units became an order for
one unit. Every numeric tool parameter uses one of these types, which refuse booleans before that
conversion; the JSON schema stays "number" / "integer".
"""

from typing import Annotated, Any

from pydantic import BeforeValidator


def _not_a_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("a number is required, not true/false")
    return value


Number = Annotated[float, BeforeValidator(_not_a_bool)]
Integer = Annotated[int, BeforeValidator(_not_a_bool)]
