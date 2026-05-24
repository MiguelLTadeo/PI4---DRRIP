"""
DRRIP (Dynamic Re-Reference Interval Prediction).

Baseado em Jaleel et al., "High Performance Cache Replacement using
Re-Reference Interval Prediction (RRIP)", ISCA-37, 2010.

Conceitos-chave:
----------------
RRPV (Re-reference Prediction Value), M bits por linha. Aqui M=2 (4 valores).
    0  = re-referência iminente
    1  = re-referência intermediária
    2  = re-referência "long" (intervalo longo) - usado na inserção SRRIP
    3  = re-referência "distant" (distante) - candidato preferencial à eviction

SRRIP (Static RRIP) - Hit Priority:
    - Inserção: RRPV = 2 (long)
    - Hit:      RRPV = 0 (promoção MRU)
    - Vítima:   primeiro com RRPV = 3; se não há, envelhece todos (+1) e repete.
    - Resistente a "scans" mas sofre em cargas thrashing.

BRRIP (Bimodal RRIP):
    - Inserção: maioria com RRPV = 3 (distant); com probabilidade ε = 1/32,
      insere com RRPV = 2 (long). Preserva parte do working set quando este é
      maior que a cache (resistente a thrashing).
    - Hit:      idêntico ao SRRIP-HP (RRPV = 0).
    - Vítima:   idêntica ao SRRIP.

DRRIP usa Set Dueling [Qureshi'07] para escolher dinamicamente:
    - 32 sets "dedicados" a SRRIP (SDM_SRRIP)
    - 32 sets "dedicados" a BRRIP (SDM_BRRIP)
    - Restantes ("followers") seguem a política vencedora segundo PSEL (10 bits).
    - PSEL: incrementa em miss de SDM_SRRIP, decrementa em miss de SDM_BRRIP.
            MSB(PSEL) == 1 -> SRRIP perdeu -> followers usam BRRIP.

Overhead vs. LRU (n vias):
    LRU:   n * log2(n) bits/conjunto
    DRRIP: 2*n bits/conjunto + 10 bits (PSEL global) -> economia para n >= 4.
"""

from __future__ import annotations

import random

from .cache import Cache


class DRRIPCache(Cache):
    """Cache DRRIP com SRRIP-HP + BRRIP + Set Dueling."""

    # Parâmetros do RRIP
    M = 2                       # bits do RRPV
    MAX_RRPV = (1 << M) - 1     # 3 -> "distant"
    LONG_RRPV = (1 << M) - 2    # 2 -> "long"

    # Parâmetros do Set Dueling
    SDM_SETS_PER_POLICY = 32
    PSEL_BITS = 10
    PSEL_MAX = (1 << PSEL_BITS) - 1
    PSEL_INIT = 1 << (PSEL_BITS - 1)   # ponto médio (512)
    BRRIP_EPSILON_DENOM = 32           # ε = 1/32 (a cada 32 inserções BRRIP, 1 é "long")

    def __init__(
        self,
        name: str,
        total_size: int,
        block_size: int,
        associativity: int,
        seed: int = 42,
        policy: str = "DRRIP",
    ):
        """
        Parameters
        ----------
        policy : {"DRRIP", "SRRIP", "BRRIP"}
            "DRRIP" liga set dueling. "SRRIP" / "BRRIP" forçam a política
            em todos os conjuntos (úteis para estudos de ablação).
        """
        super().__init__(name, total_size, block_size, associativity)
        assert policy in ("DRRIP", "SRRIP", "BRRIP")
        self.policy = policy

        # Inicializa todos os RRPVs em MAX (distant); linhas inválidas mesmo
        for s in range(self.num_sets):
            for way in range(self.associativity):
                self.sets[s][way].rrpv = self.MAX_RRPV

        # Set Dueling
        n_sdm = min(self.SDM_SETS_PER_POLICY, max(1, self.num_sets // 4))
        # Seleção determinística (semente fixa) para que execuções sejam reproduzíveis
        rng_assign = random.Random(0xC0FFEE)
        all_sets = list(range(self.num_sets))
        rng_assign.shuffle(all_sets)
        self.srrip_sdm_sets = frozenset(all_sets[:n_sdm])
        self.brrip_sdm_sets = frozenset(all_sets[n_sdm:2 * n_sdm])

        self.psel = self.PSEL_INIT
        # Contador determinístico por-set para o ε do BRRIP. Usar contadores
        # por-set evita correlações artificiais entre SDM_BRRIP e followers
        # quando todos compartilhariam um único contador global.
        self._brrip_counter_per_set = [0] * self.num_sets
        self.rng = random.Random(seed)

    # ----------------------- helpers de política ----------------------------

    def _is_srrip_sdm(self, set_idx: int) -> bool:
        return set_idx in self.srrip_sdm_sets

    def _is_brrip_sdm(self, set_idx: int) -> bool:
        return set_idx in self.brrip_sdm_sets

    def _follower_uses_brrip(self) -> bool:
        """PSEL alto => SRRIP teve mais misses => followers usam BRRIP."""
        return self.psel >= self.PSEL_INIT

    def _decide_policy_for_set(self, set_idx: int) -> str:
        if self.policy == "SRRIP":
            return "SRRIP"
        if self.policy == "BRRIP":
            return "BRRIP"
        # DRRIP
        if self._is_srrip_sdm(set_idx):
            return "SRRIP"
        if self._is_brrip_sdm(set_idx):
            return "BRRIP"
        return "BRRIP" if self._follower_uses_brrip() else "SRRIP"

    def _brrip_insert_rrpv(self, set_idx: int) -> int:
        """Inserção bimodal: 1 em cada 32 com RRPV=long, demais com RRPV=distant.

        O contador é por-set para que cada conjunto receba sua própria
        sequência de inserções "long", evitando correlação artificial entre
        os SDM_BRRIP e os followers em modo BRRIP.
        """
        self._brrip_counter_per_set[set_idx] += 1
        if self._brrip_counter_per_set[set_idx] % self.BRRIP_EPSILON_DENOM == 0:
            return self.LONG_RRPV
        return self.MAX_RRPV

    # -------------------------- API principal -------------------------------

    def access(self, addr: int) -> bool:
        set_idx = self.get_set_index(addr)
        tag = self.get_tag(addr)
        way = self.find_way(set_idx, tag)

        if way >= 0:
            # ----- HIT (política Hit Priority: RRPV -> 0) -----
            self.hits += 1
            self.sets[set_idx][way].rrpv = 0
            return True

        # ----- MISS -----
        self.misses += 1
        b = self.block_addr(addr)
        if b not in self._touched_blocks:
            self.compulsory_misses += 1
            self._touched_blocks.add(b)

        # Atualiza PSEL conforme o conjunto seja SDM (apenas em modo DRRIP)
        if self.policy == "DRRIP":
            if self._is_srrip_sdm(set_idx):
                if self.psel < self.PSEL_MAX:
                    self.psel += 1
            elif self._is_brrip_sdm(set_idx):
                if self.psel > 0:
                    self.psel -= 1

        # Política efetiva para este conjunto
        active = self._decide_policy_for_set(set_idx)
        if active == "SRRIP":
            insert_rrpv = self.LONG_RRPV
        else:  # BRRIP
            insert_rrpv = self._brrip_insert_rrpv(set_idx)

        # Seleção da vítima
        victim = self._find_victim(set_idx)

        line = self.sets[set_idx][victim]
        line.valid = True
        line.tag = tag
        line.rrpv = insert_rrpv
        return False

    # --------------------------- victim search ------------------------------

    def _find_victim(self, set_idx: int) -> int:
        """RRIP: encontra primeiro way com RRPV == MAX_RRPV (distant).
        Se nenhum existe, envelhece todos (RRPV += 1, saturando em MAX) e
        repete a busca. Como a quantidade de incrementos por chamada é
        limitada por MAX_RRPV, esse loop sempre termina.

        Prefere preencher linhas inválidas primeiro (cold start).
        """
        # 1) Linha livre tem precedência
        inv = self.find_invalid_way(set_idx)
        if inv >= 0:
            return inv

        cset = self.sets[set_idx]
        # 2) Busca + aging até encontrar RRPV = MAX
        for _ in range(self.MAX_RRPV + 1):  # cota de segurança
            for way in range(self.associativity):
                if cset[way].rrpv == self.MAX_RRPV:
                    return way
            # Envelhece todos
            for way in range(self.associativity):
                if cset[way].rrpv < self.MAX_RRPV:
                    cset[way].rrpv += 1
        # Garantia: após no máximo MAX_RRPV incrementos algum way satura
        return 0  # nunca deveria chegar aqui

    # ------------------------------- overhead -------------------------------

    def storage_overhead_bits(self) -> int:
        """Bits de metadados: 1 valid + tag + M bits de RRPV + (10 bits PSEL globais)."""
        tag_bits = 32 - self.offset_bits - self.index_bits
        per_line = 1 + tag_bits + self.M
        total = self.num_sets * self.associativity * per_line
        if self.policy == "DRRIP":
            total += self.PSEL_BITS  # contador global
        return total
