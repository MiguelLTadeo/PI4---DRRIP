"""
Cache base (set-associative) - modelagem funcional.

Este módulo define a estrutura genérica de uma cache set-associativa,
sem comprometer-se com uma política de substituição específica.
As políticas (LRU, DRRIP) herdam de Cache e implementam access().

Endereço (assumindo arquitetura RV32I, 32 bits):

    +-----+-----+--------+
    | tag | idx | offset |
    +-----+-----+--------+

- offset_bits = log2(block_size)
- index_bits  = log2(num_sets)
- tag_bits    = 32 - offset_bits - index_bits
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class CacheLine:
    """Uma linha (way) de cache.

    Os campos abrangem o estado necessário para LRU e DRRIP:
      - valid, tag: comuns
      - lru_age:    contador de idade para LRU (0 = MRU, n-1 = LRU)
      - rrpv:       Re-reference Prediction Value, 2 bits para DRRIP
    """
    valid: bool = False
    tag: int = 0
    lru_age: int = 0
    rrpv: int = 3  # inicia em "distant" (para DRRIP / SRRIP)


class Cache:
    """Cache set-associativa genérica.

    Parâmetros
    ----------
    name : str
        Identificador (ex.: "L1D", "L2").
    total_size : int
        Capacidade em bytes (potência de 2).
    block_size : int
        Tamanho do bloco em bytes (potência de 2).
    associativity : int
        Número de vias por conjunto (potência de 2).
    """

    def __init__(self, name: str, total_size: int, block_size: int, associativity: int):
        assert total_size % (block_size * associativity) == 0, (
            "total_size deve ser múltiplo de block_size * associativity"
        )
        for v in (total_size, block_size, associativity):
            assert (v & (v - 1)) == 0 and v > 0, f"{v} deve ser potência de 2"

        self.name = name
        self.total_size = total_size
        self.block_size = block_size
        self.associativity = associativity
        self.num_sets = total_size // (block_size * associativity)

        self.offset_bits = int(math.log2(block_size))
        self.index_bits = int(math.log2(self.num_sets))

        # Aloca os conjuntos como matriz [num_sets][associativity] de CacheLine
        self.sets: list[list[CacheLine]] = [
            [CacheLine() for _ in range(associativity)]
            for _ in range(self.num_sets)
        ]

        # Estatísticas
        self.hits = 0
        self.misses = 0
        # Para detectar misses obrigatórios (primeira vez que o bloco é tocado)
        self._touched_blocks: set[int] = set()
        self.compulsory_misses = 0

    # -------------------------- decomposição de endereço --------------------

    def get_set_index(self, addr: int) -> int:
        return (addr >> self.offset_bits) & (self.num_sets - 1)

    def get_tag(self, addr: int) -> int:
        return addr >> (self.offset_bits + self.index_bits)

    def block_addr(self, addr: int) -> int:
        """Endereço alinhado ao bloco (usado para contabilizar compulsórios)."""
        return addr & ~(self.block_size - 1)

    # -------------------------- busca em conjunto ---------------------------

    def find_way(self, set_idx: int, tag: int) -> int:
        """Retorna o way que contém tag no conjunto, ou -1 se ausente."""
        for way, line in enumerate(self.sets[set_idx]):
            if line.valid and line.tag == tag:
                return way
        return -1

    def find_invalid_way(self, set_idx: int) -> int:
        """Retorna primeiro way inválido (livre) no conjunto, ou -1."""
        for way, line in enumerate(self.sets[set_idx]):
            if not line.valid:
                return way
        return -1

    # -------------------------- interface pública ---------------------------

    def access(self, addr: int) -> bool:
        """A ser implementado pelas subclasses. Retorna True em hit."""
        raise NotImplementedError

    @property
    def total_accesses(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total_accesses if self.total_accesses else 0.0

    @property
    def miss_rate(self) -> float:
        return self.misses / self.total_accesses if self.total_accesses else 0.0

    def reset_stats(self) -> None:
        self.hits = 0
        self.misses = 0
        self.compulsory_misses = 0
        self._touched_blocks.clear()

    def reset_state(self) -> None:
        """Limpa o conteúdo da cache (invalida todas as linhas)."""
        for cset in self.sets:
            for line in cset:
                line.valid = False
                line.tag = 0
                line.lru_age = 0
                line.rrpv = 3
        self.reset_stats()

    # -------------------------- overhead em bits ----------------------------

    def storage_overhead_bits(self) -> int:
        """Bits de metadados/política por cache (a ser sobrescrito)."""
        # Por linha: 1 bit válido + tag_bits
        tag_bits = 32 - self.offset_bits - self.index_bits
        return self.num_sets * self.associativity * (1 + tag_bits)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}({self.name}, "
                f"{self.total_size//1024}KB, "
                f"block={self.block_size}B, "
                f"assoc={self.associativity}, "
                f"sets={self.num_sets})")
