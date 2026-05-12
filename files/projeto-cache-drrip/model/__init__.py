"""Modelagem funcional de caches inteligentes em Python (semanas 1-4).

Política baseline:        LRU (LRUCache em lru.py)
Política proposta:        DRRIP (DRRIPCache em drrip.py)
Algoritmos auxiliares:    SRRIP e BRRIP (subcasos do DRRIPCache)

Para uso:
    from model.lru   import LRUCache
    from model.drrip import DRRIPCache
    from model.memory_hierarchy import MemoryHierarchy
    from model.benchmarks       import streaming_hotset
"""

from .cache import Cache, CacheLine
from .lru import LRUCache
from .drrip import DRRIPCache
from .memory_hierarchy import MemoryHierarchy
from .benchmarks import (
    streaming_hotset,
    matrix_convolution,
    linked_list,
    pattern_search,
    mixed_access_pattern,
    BENCHMARKS,
)

__all__ = [
    "Cache", "CacheLine",
    "LRUCache", "DRRIPCache",
    "MemoryHierarchy",
    "streaming_hotset", "matrix_convolution",
    "linked_list", "pattern_search", "mixed_access_pattern",
    "BENCHMARKS",
]
