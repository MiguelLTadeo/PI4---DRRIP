"""
LRU (Least Recently Used) - baseline.

Implementação verdadeira de LRU (não aproximação como NRU/PLRU).
Cada linha mantém um "lru_age": 0 = MRU, associativity-1 = LRU.

Em cache hit:
    1. Identifica idade atual do way que acertou.
    2. Envelhece todos os ways com idade menor que ele.
    3. Marca o way que acertou como MRU (idade 0).

Em cache miss:
    1. Procura linha inválida; se não há, escolhe a de maior idade (LRU).
    2. Insere o bloco no way escolhido e o marca como MRU.

Overhead (n vias): n * log2(n) bits por conjunto + 1 bit valid + tag.
"""

from __future__ import annotations

import math

from .cache import Cache


class LRUCache(Cache):
    """Cache com substituição LRU verdadeira."""

    def __init__(self, name: str, total_size: int, block_size: int, associativity: int):
        super().__init__(name, total_size, block_size, associativity)
        # Inicializa idades 0..n-1 (arbitrário, todas inválidas mesmo)
        for s in range(self.num_sets):
            for way in range(self.associativity):
                self.sets[s][way].lru_age = way

    def access(self, addr: int) -> bool:
        set_idx = self.get_set_index(addr)
        tag = self.get_tag(addr)
        way = self.find_way(set_idx, tag)

        if way >= 0:
            # ----- HIT -----
            self.hits += 1
            self._on_hit(set_idx, way)
            return True

        # ----- MISS -----
        self.misses += 1
        b = self.block_addr(addr)
        if b not in self._touched_blocks:
            self.compulsory_misses += 1
            self._touched_blocks.add(b)

        # Procura linha livre; se não há, escolhe LRU
        victim = self.find_invalid_way(set_idx)
        if victim < 0:
            victim = self._find_lru_way(set_idx)

        # Insere e marca como MRU; envelhece as demais linhas válidas
        self.sets[set_idx][victim].valid = True
        self.sets[set_idx][victim].tag = tag
        self._insert_as_mru(set_idx, victim)
        return False

    # ------------------------------- internos -------------------------------

    def _on_hit(self, set_idx: int, hit_way: int) -> None:
        """Em hit: envelhece linhas com idade menor que a do hit; MRU para 0.

        Invariante: linhas válidas têm idades distintas em {0..k-1}.
        """
        prev_age = self.sets[set_idx][hit_way].lru_age
        for way in range(self.associativity):
            line = self.sets[set_idx][way]
            if way == hit_way:
                continue
            if line.valid and line.lru_age < prev_age:
                line.lru_age += 1
        self.sets[set_idx][hit_way].lru_age = 0

    def _insert_as_mru(self, set_idx: int, new_way: int) -> None:
        """Em miss: a nova linha é inserida na posição MRU; TODAS as outras
        linhas válidas envelhecem em 1 (preservando a invariante de idades
        distintas mesmo se o conjunto ainda contiver linhas inválidas).
        """
        max_age = self.associativity - 1
        for way in range(self.associativity):
            line = self.sets[set_idx][way]
            if way == new_way:
                continue
            if line.valid and line.lru_age < max_age:
                line.lru_age += 1
        self.sets[set_idx][new_way].lru_age = 0

    def _find_lru_way(self, set_idx: int) -> int:
        """Retorna o way com maior idade (= LRU)."""
        max_age = -1
        victim = 0
        for way in range(self.associativity):
            if self.sets[set_idx][way].lru_age > max_age:
                max_age = self.sets[set_idx][way].lru_age
                victim = way
        return victim

    # ------------------------------- overhead -------------------------------

    def storage_overhead_bits(self) -> int:
        """Bits de metadados, incluindo contadores de idade para LRU.

        Por linha:  1 (valid) + tag_bits + log2(assoc) (idade)
        """
        tag_bits = 32 - self.offset_bits - self.index_bits
        age_bits = int(math.log2(self.associativity))
        per_line = 1 + tag_bits + age_bits
        return self.num_sets * self.associativity * per_line
