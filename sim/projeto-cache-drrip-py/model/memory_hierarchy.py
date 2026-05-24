"""
Hierarquia de memória: L1D privada + L2 (data) compartilhada.

Para a fase de modelagem (semanas 1-4) consideramos apenas o caminho de
dados: L1D -> L2 -> memória principal. A unificação da L2 (dados +
instruções) será introduzida na fase de integração com o core RISC-V
(semanas 9-12); o modelo aqui foca em validar o hit rate lógico do
algoritmo de substituição.

Política de inclusão: NON-INCLUSIVE / NON-EXCLUSIVE.
    - Um miss em L1 dispara uma consulta em L2.
    - Se L2 também miss, supõe-se busca na memória principal e o bloco é
      inserido nas duas (L1 traz 32B, L2 traz 64B que contém os 32B).
    - Sem modelagem explícita de write-back; as escritas tratam-se como
      acessos comuns para fins de hit rate.
"""

from __future__ import annotations

from .cache import Cache


class MemoryHierarchy:
    """Empacota L1D e L2 e contabiliza acessos/latência."""

    # Latências em ciclos (estimativas conservadoras para um core RV32I simples)
    L1_LATENCY = 1
    L2_LATENCY = 10
    MEM_LATENCY = 100

    def __init__(self, l1d: Cache, l2: Cache):
        self.l1d = l1d
        self.l2 = l2
        self.total_cycles = 0
        self.l1d_accesses = 0
        self.l2_accesses = 0
        self.mem_accesses = 0

    def access(self, addr: int) -> int:
        """Acessa o endereço de dados e retorna a latência (ciclos)."""
        self.l1d_accesses += 1
        if self.l1d.access(addr):
            self.total_cycles += self.L1_LATENCY
            return self.L1_LATENCY

        # L1 miss -> consulta L2
        self.l2_accesses += 1
        if self.l2.access(addr):
            lat = self.L1_LATENCY + self.L2_LATENCY
        else:
            self.mem_accesses += 1
            lat = self.L1_LATENCY + self.L2_LATENCY + self.MEM_LATENCY
        self.total_cycles += lat
        return lat

    # -------------------------------- métricas ------------------------------

    def reset_stats(self) -> None:
        self.l1d.reset_stats()
        self.l2.reset_stats()
        self.total_cycles = 0
        self.l1d_accesses = 0
        self.l2_accesses = 0
        self.mem_accesses = 0

    def reset_state(self) -> None:
        self.l1d.reset_state()
        self.l2.reset_state()
        self.total_cycles = 0
        self.l1d_accesses = 0
        self.l2_accesses = 0
        self.mem_accesses = 0

    def summary(self) -> dict:
        """Resumo numérico das métricas principais."""
        l1d_hr = self.l1d.hit_rate
        l2_hr = self.l2.hit_rate
        # AMAT teórico (Average Memory Access Time)
        if self.l1d_accesses:
            amat = (
                self.L1_LATENCY
                + (1 - l1d_hr) * (
                    self.L2_LATENCY
                    + (1 - l2_hr) * self.MEM_LATENCY
                )
            )
        else:
            amat = 0.0
        return {
            "l1d_hits": self.l1d.hits,
            "l1d_misses": self.l1d.misses,
            "l1d_hit_rate": l1d_hr,
            "l2_hits": self.l2.hits,
            "l2_misses": self.l2.misses,
            "l2_hit_rate": l2_hr,
            "l1d_accesses": self.l1d_accesses,
            "l2_accesses": self.l2_accesses,
            "mem_accesses": self.mem_accesses,
            "total_cycles": self.total_cycles,
            "amat_cycles": amat,
            "compulsory_misses_l1d": self.l1d.compulsory_misses,
            "compulsory_misses_l2": self.l2.compulsory_misses,
        }
