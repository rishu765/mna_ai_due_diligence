"""Trusted process-local checkpoint serialization for the offline V1."""

from __future__ import annotations

import pickle
from typing import Any


class TrustedLocalSerializer:
    """Preserve immutable domain objects in a trusted in-process store only."""

    _TYPE = "madd-trusted-local-pickle-v1"

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        return self._TYPE, pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        kind, payload = data
        if kind != self._TYPE:
            raise ValueError(f"unsupported local checkpoint payload type: {kind}")
        return pickle.loads(payload)  # noqa: S301 - trusted same-process data only
