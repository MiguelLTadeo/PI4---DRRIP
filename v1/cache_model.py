"""
cache_model.py
==============
Modelo funcional da hierarquia de memoria (L1I, L1D, L2 unificada) com
suporte a duas politicas de substituicao:
  - LRU  (baseline)
  - DRRIP (Dynamic Re-Reference Interval Prediction, Jaleel et al. ISCA 2010)

Este modelo NAO tenta ser ciclo-acurado. Ele e' funcional: para cada acesso
de memoria, decide hit/miss e atualiza estado de substituicao exatamente
como a versao Verilog devera fazer. E' a referencia dourada (golden model)
usada para validar o testbench Verilog depois.

Convencoes:
  - Endereco e' inteiro (32 bits); enderecos nao validos serao mascarados.
  - Cada acesso e' uma tupla (addr, kind), onde kind in {'I','R','W'}.
      'I' = instruction fetch  (vai para L1I, miss desce para L2)
      'R' = data read          (vai para L1D, miss desce para L2)
      'W' = data write         (write-through simples; ainda assim consulta
                                hit/miss em L1D e L2)

Notas de modelagem que CASAM com a especificacao do projeto:
  - L1D: 4-8 KB, bloco 32 B, assoc 2 ou 4 vias.
  - L2 unificada: 32-128 KB, bloco 64 B, assoc 8 ou 16 vias.
  - L1I tem mesmas dimensoes de L1D (especificacao exige duas L1).
  - L2 e' unificada (recebe miss de L1I e L1D).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
import math


# ---------------------------------------------------------------------------
# Bloco de cache (uma "linha" / "way")
# ---------------------------------------------------------------------------

@dataclass
class Line:
    """Uma linha de cache. Carrega tag, valid, e metadados de substituicao."""
    valid: bool = False
    tag: int = 0
    # Para LRU: posicao no stack (0 = MRU, assoc-1 = LRU)
    lru_pos: int = 0
    # Para DRRIP: Re-Reference Prediction Value (M bits, tipicamente M=2)
    rrpv: int = 0


# ---------------------------------------------------------------------------
# Cache generica configuravel
# ---------------------------------------------------------------------------

class Cache:
    """
    Cache set-associative parametrizavel.

    Parametros:
      size_bytes : capacidade total em bytes (data store; nao conta tags)
      block_size : tamanho do bloco em bytes
      assoc      : numero de vias (associatividade)
      policy     : 'LRU' ou 'DRRIP'
      rrpv_bits  : numero de bits do RRPV (so para DRRIP). M=2 -> RRPV em [0,3]
      name       : rotulo (para impressao/log)
      sd_constituency : tamanho da "constituency" do set dueling (DRRIP).
                        Tipicamente 32 ou 64. Define quantos sets sao
                        amostrados como dedicated-SRRIP e dedicated-BRRIP.
    """

    # Probabilidade de inserir com RRPV=long (=2^M-2) no BRRIP.
    # Paper original usa 1/32 (≈3%). Implementamos com contador determinístico
    # para que a versao Verilog seja exatamente reproduzivel.
    BRRIP_LONG_PROB = 32  # 1 em 32 insercoes vai com RRPV=long

    def __init__(self, size_bytes: int, block_size: int, assoc: int,
                 policy: str = 'LRU', rrpv_bits: int = 2,
                 name: str = 'cache', sd_constituency: int = 32):
        assert policy in ('LRU', 'DRRIP'), f"policy invalida: {policy}"
        assert size_bytes % (block_size * assoc) == 0, \
            "size_bytes deve ser multiplo de block_size*assoc"

        self.size_bytes = size_bytes
        self.block_size = block_size
        self.assoc = assoc
        self.policy = policy
        self.rrpv_bits = rrpv_bits
        self.rrpv_max = (1 << rrpv_bits) - 1   # ex: M=2 -> 3
        self.rrpv_long = self.rrpv_max - 1     # ex: M=2 -> 2 (insercao SRRIP)
        self.rrpv_distant = self.rrpv_max      # ex: M=2 -> 3 (insercao BRRIP "fria")
        self.name = name

        self.num_sets = size_bytes // (block_size * assoc)
        self.offset_bits = int(math.log2(block_size))
        self.index_bits = int(math.log2(self.num_sets))

        # Estrutura: lista de sets, cada set e' uma lista de Lines.
        self.sets: List[List[Line]] = [
            [Line() for _ in range(assoc)] for _ in range(self.num_sets)
        ]

        # Contadores
        self.hits = 0
        self.misses = 0
        self.accesses = 0

        # ------------- Estado especifico do DRRIP -------------
        # PSEL: contador saturado de 10 bits (0..1023). MSB define politica
        # follower. Comecamos no meio (512).
        self.psel_bits = 10
        self.psel_max = (1 << self.psel_bits) - 1
        self.psel = self.psel_max // 2

        # Contador de insercoes BRRIP, para implementacao deterministica
        # do bimodal throttle (1 em BRRIP_LONG_PROB).
        self.brrip_counter = 0

        # Identifica conjuntos "dedicated SRRIP" e "dedicated BRRIP" pelo
        # esquema de bits cruzados ("complementary set indexing"). Para
        # cada set index, computamos high_bits XOR low_bits e usamos para
        # rotular. Eh determinístico e replicavel em hardware.
        # Em Verilog: comparar constituency_id contra um padrao fixo.
        self._sd_mask = sd_constituency - 1  # ex: 32 -> mask 5 bits
        self._dedicated_srrip_pattern = 0
        self._dedicated_brrip_pattern = self._sd_mask  # padrao oposto

    # ---------- Helpers de endereco ----------
    def _decompose(self, addr: int) -> Tuple[int, int]:
        """Retorna (tag, set_index) para um endereco."""
        block_addr = addr >> self.offset_bits
        set_index = block_addr & (self.num_sets - 1)
        tag = block_addr >> self.index_bits
        return tag, set_index

    def _is_dedicated_srrip(self, set_idx: int) -> bool:
        """Set dueling: este set e' SRRIP-dedicado?"""
        # Particao simples: pega bits altos do indice como "constituency id"
        # e bits baixos como "offset dentro da constituency". O set offset 0
        # de cada constituency vira SRRIP-dedicado.
        return (set_idx & self._sd_mask) == self._dedicated_srrip_pattern

    def _is_dedicated_brrip(self, set_idx: int) -> bool:
        """Set dueling: este set e' BRRIP-dedicado?"""
        return (set_idx & self._sd_mask) == self._dedicated_brrip_pattern

    def _follower_policy_is_srrip(self) -> bool:
        """Politica que os sets follower seguem (controlada pelo MSB de PSEL)."""
        # PSEL alto -> SRRIP esta perdendo (gerando muitos misses) -> seguir BRRIP.
        # PSEL baixo -> BRRIP esta perdendo -> seguir SRRIP.
        msb = self.psel >> (self.psel_bits - 1)
        return msb == 0

    # ---------- API publica ----------
    def access(self, addr: int) -> bool:
        """Faz um acesso. Retorna True em hit, False em miss."""
        self.accesses += 1
        tag, set_idx = self._decompose(addr)
        cache_set = self.sets[set_idx]

        # 1) Busca por hit
        for way, line in enumerate(cache_set):
            if line.valid and line.tag == tag:
                self.hits += 1
                self._on_hit(set_idx, way)
                return True

        # 2) Miss: precisa instalar
        self.misses += 1
        self._on_miss(set_idx, tag)
        return False

    # ---------- Logica de hit (depende da politica) ----------
    def _on_hit(self, set_idx: int, way: int) -> None:
        if self.policy == 'LRU':
            self._lru_promote(set_idx, way)
        else:  # DRRIP
            # Hit Promotion: bloco que deu hit vai para RRPV=0 (re-referencia
            # iminente). Isso e' o "HP" do RRIP.
            self.sets[set_idx][way].rrpv = 0

    # ---------- Logica de miss (depende da politica) ----------
    def _on_miss(self, set_idx: int, tag: int) -> None:
        if self.policy == 'LRU':
            victim = self._lru_pick_victim(set_idx)
            self._lru_install(set_idx, victim, tag)
        else:  # DRRIP
            victim = self._drrip_pick_victim(set_idx)
            self._drrip_install(set_idx, victim, tag)
            # Atualiza PSEL se este set e' dedicado.
            if self._is_dedicated_srrip(set_idx):
                # SRRIP errou: PSEL++ (SRRIP esta perdendo)
                if self.psel < self.psel_max:
                    self.psel += 1
            elif self._is_dedicated_brrip(set_idx):
                # BRRIP errou: PSEL-- (BRRIP esta perdendo)
                if self.psel > 0:
                    self.psel -= 1

    # ============= LRU =============
    def _lru_pick_victim(self, set_idx: int) -> int:
        cache_set = self.sets[set_idx]
        # Primeiro, prefere uma linha invalida (cache fria).
        for way, line in enumerate(cache_set):
            if not line.valid:
                return way
        # Senao, escolhe a com lru_pos == assoc-1 (mais antiga).
        for way, line in enumerate(cache_set):
            if line.lru_pos == self.assoc - 1:
                return way
        return 0  # fallback (nao deveria ocorrer)

    def _lru_install(self, set_idx: int, way: int, tag: int) -> None:
        """Instala um bloco novo na via 'way'. Como e' insercao (nao
        promocao), TODAS as outras linhas validas envelhecem (lru_pos+=1)
        antes da nova entrar como MRU.

        Importante: a distincao entre _lru_install e _lru_promote e' critica.
        Na promocao (hit), so envelhecem as linhas que estavam mais novas
        que a vitima. Na instalacao (miss), a via que vai receber o bloco
        e' nova - todas as validas anteriores envelhecem em relacao a ela.
        """
        cache_set = self.sets[set_idx]
        # Envelhece todas as VALIDAS que ja estao no set (antes de marcar a
        # nova como valida).
        for ln in cache_set:
            if ln.valid and ln.lru_pos < self.assoc - 1:
                ln.lru_pos += 1
        # Marca a nova como valida e MRU.
        cache_set[way].valid = True
        cache_set[way].tag = tag
        cache_set[way].lru_pos = 0

    def _lru_promote(self, set_idx: int, way: int) -> None:
        """Hit: move a via 'way' para topo do stack LRU (pos 0).
        So envelhecem as linhas que estavam MAIS NOVAS que 'way'
        (lru_pos < old_pos do way)."""
        cache_set = self.sets[set_idx]
        old_pos = cache_set[way].lru_pos
        for ln in cache_set:
            if ln.valid and ln.lru_pos < old_pos:
                ln.lru_pos += 1
        cache_set[way].lru_pos = 0

    # ============= DRRIP =============
    def _drrip_pick_victim(self, set_idx: int) -> int:
        """Procura um bloco com RRPV=max. Se nao houver, incrementa todos."""
        cache_set = self.sets[set_idx]

        # Cache fria: prefere invalida.
        for way, line in enumerate(cache_set):
            if not line.valid:
                return way

        # Procura RRPV maximo, incrementando se necessario.
        # ATENCAO: este loop tem no maximo (rrpv_max + 1) iteracoes na pratica,
        # ja que eventualmente alguem vai chegar a max. Em hardware vira
        # uma maquina de estados de poucos ciclos OU pode ser feito em
        # combinacional dentro de 1 ciclo (depende da Fmax alvo).
        while True:
            for way, line in enumerate(cache_set):
                if line.rrpv == self.rrpv_max:
                    return way
            # Ninguem em max: incrementa todos.
            for line in cache_set:
                if line.rrpv < self.rrpv_max:
                    line.rrpv += 1

    def _decide_insertion_rrpv(self, set_idx: int) -> int:
        """Decide com qual RRPV o novo bloco entra. Implementa o set dueling."""
        # 1) Sets dedicados ignoram PSEL: usam politica fixa.
        if self._is_dedicated_srrip(set_idx):
            use_srrip = True
        elif self._is_dedicated_brrip(set_idx):
            use_srrip = False
        else:
            # Follower segue MSB de PSEL.
            use_srrip = self._follower_policy_is_srrip()

        if use_srrip:
            # SRRIP: insere com long (rrpv = max-1, ex.: 2)
            return self.rrpv_long
        else:
            # BRRIP: insere com distant (rrpv = max, ex.: 3) na maioria,
            # mas 1 em BRRIP_LONG_PROB vai com long (cria caminho para
            # a politica eventualmente recompensar reuso).
            self.brrip_counter += 1
            if self.brrip_counter % self.BRRIP_LONG_PROB == 0:
                return self.rrpv_long
            else:
                return self.rrpv_distant

    def _drrip_install(self, set_idx: int, way: int, tag: int) -> None:
        cache_set = self.sets[set_idx]
        cache_set[way].valid = True
        cache_set[way].tag = tag
        cache_set[way].rrpv = self._decide_insertion_rrpv(set_idx)

    # ---------- Estatisticas ----------
    @property
    def hit_rate(self) -> float:
        return self.hits / self.accesses if self.accesses else 0.0

    @property
    def miss_rate(self) -> float:
        return self.misses / self.accesses if self.accesses else 0.0

    def reset_stats(self) -> None:
        self.hits = 0
        self.misses = 0
        self.accesses = 0

    def __repr__(self) -> str:
        return (f"Cache({self.name}, {self.size_bytes}B, "
                f"block={self.block_size}, assoc={self.assoc}, "
                f"sets={self.num_sets}, policy={self.policy})")


# ---------------------------------------------------------------------------
# Hierarquia: L1I + L1D + L2 unificada
# ---------------------------------------------------------------------------

class MemoryHierarchy:
    """
    Hierarquia conforme especificacao:
      - L1I: cache de instrucoes
      - L1D: cache de dados
      - L2 : unificada (recebe miss de L1I e L1D)

    Politica: a especificacao manda aplicar o algoritmo (LRU ou DRRIP)
    em TODAS as caches.
    """

    def __init__(self, l1d_size: int, l1d_assoc: int,
                 l1_block: int,
                 l2_size: int, l2_assoc: int, l2_block: int,
                 policy: str = 'LRU'):
        # L1I com mesmas dimensoes de L1D (especificacao mostra so L1D na
        # tabela mas exige duas L1; interpretamos como simetricas).
        self.l1i = Cache(l1d_size, l1_block, l1d_assoc, policy=policy, name='L1I')
        self.l1d = Cache(l1d_size, l1_block, l1d_assoc, policy=policy, name='L1D')
        self.l2  = Cache(l2_size,  l2_block, l2_assoc,  policy=policy, name='L2 ')
        self.policy = policy

    def access(self, addr: int, kind: str) -> Dict[str, bool]:
        """
        Faz um acesso e propaga miss para L2 quando aplicavel.
        Retorna dict com hits/miss em cada nivel (para inspecao).
        """
        result = {'l1i_hit': None, 'l1d_hit': None, 'l2_hit': None}

        if kind == 'I':
            hit = self.l1i.access(addr)
            result['l1i_hit'] = hit
            if not hit:
                # Miss em L1I -> consulta L2
                result['l2_hit'] = self.l2.access(addr)
        else:  # 'R' ou 'W'
            hit = self.l1d.access(addr)
            result['l1d_hit'] = hit
            if not hit:
                result['l2_hit'] = self.l2.access(addr)
        return result

    def report(self) -> Dict[str, float]:
        return {
            'L1I_hit_rate': self.l1i.hit_rate,
            'L1D_hit_rate': self.l1d.hit_rate,
            'L2_hit_rate':  self.l2.hit_rate,
            'L1I_accesses': self.l1i.accesses,
            'L1D_accesses': self.l1d.accesses,
            'L2_accesses':  self.l2.accesses,
            'overall_hit_rate': (
                (self.l1i.hits + self.l1d.hits + self.l2.hits) /
                max(1, self.l1i.accesses + self.l1d.accesses + self.l2.accesses)
            ),
        }
