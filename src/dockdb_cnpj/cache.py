"""
Cache TTL (LRU) e rate limit por janela deslizante, em memória e thread-safe.

Usados pela API; cada processo/worker do uvicorn tem os seus.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Any

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

Clock = Callable[[], float]


class TTLCache:
    def __init__(self, ttl: float, max_items: int, *, clock: Clock = time.monotonic) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            expira, valor = item
            if self._clock() >= expira:
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return valor

    def set(self, key: str, valor: Any) -> None:
        with self._lock:
            self._data[key] = (self._clock() + self.ttl, valor)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "ttl_s": self.ttl,
                "max_itens": self.max_items,
                "itens": len(self._data),
                "hits": self.hits,
                "misses": self.misses,
            }


class RateLimiter:
    """No máximo ``limite`` requisições por ``janela`` segundos, por chave (IP)."""

    def __init__(self, limite: int, janela: float = 60.0, *, clock: Clock = time.monotonic) -> None:
        self.limite = limite
        self.janela = janela
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def permitir(self, chave: str) -> tuple[bool, int]:
        """(permitido, segundos até liberar)."""
        agora = self._clock()
        with self._lock:
            fila = self._hits.setdefault(chave, deque())
            while fila and agora - fila[0] >= self.janela:
                fila.popleft()
            if len(fila) >= self.limite:
                espera = int(self.janela - (agora - fila[0])) + 1
                return False, espera
            fila.append(agora)
            if len(self._hits) > 10_000:
                self._purge(agora)
            return True, 0

    def _purge(self, agora: float) -> None:
        for k in [k for k, f in self._hits.items() if not f or agora - f[-1] >= self.janela]:
            del self._hits[k]
