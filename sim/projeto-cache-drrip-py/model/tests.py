"""
Testes unitários de validação lógica.

Verifica:
1. Decomposição correta de endereço (offset/index/tag).
2. Hit/miss em sequências canônicas.
3. Política LRU: que o bloco LRU é, de fato, despejado.
4. Política DRRIP: que blocos "long" (RRPV=2) prevalecem sobre "distant" (RRPV=3),
   reproduzindo o exemplo da Figura 3c do artigo.
5. Estados invariantes: válidos, contagens consistentes.

Executar:  python -m model.tests   ou   pytest -q model/tests.py
"""

from __future__ import annotations

import math
import sys

from .cache import Cache
from .lru import LRUCache
from .drrip import DRRIPCache


# ---------------------------- utilitários -------------------------------------

def expect(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FALHOU: {msg}", file=sys.stderr)
        raise AssertionError(msg)
    print(f"OK     {msg}")


# ---------------------------- 1. address layout -------------------------------

def test_address_layout() -> None:
    # 4KB, 32B blocos, 2 vias -> 4096/(32*2) = 64 conjuntos
    c = LRUCache("L1D", 4096, 32, 2)
    assert c.num_sets == 64
    assert c.offset_bits == 5
    assert c.index_bits == 6
    expect(c.get_set_index(0x0) == 0,                "set_idx(0x000) == 0")
    expect(c.get_set_index(0x20) == 1,               "set_idx(0x020) == 1  (próximo bloco)")
    expect(c.get_set_index(0x800) == 0,              "set_idx(0x800) == 0  (mesma índice, tag diferente)")
    expect(c.get_tag(0x0) != c.get_tag(0x800),       "tag(0x000) != tag(0x800)")


# ---------------------------- 2. hits e misses simples ------------------------

def test_lru_basic_hit_miss() -> None:
    # Cache pequena para forçar comportamento exato
    c = LRUCache("L1D", 4096, 32, 2)
    c.reset_state()

    c.access(0x100)             # miss compulsório
    expect(c.misses == 1 and c.hits == 0, "primeiro acesso: 1 miss / 0 hit")
    c.access(0x100)             # hit
    expect(c.misses == 1 and c.hits == 1, "acesso repetido: hit")

    # Conflito no mesmo conjunto (mesmo index, tags diferentes)
    set_idx = c.get_set_index(0x100)
    block_size = c.block_size
    num_sets = c.num_sets

    # Estes 3 endereços mapeiam para o mesmo conjunto que 0x100
    same_set_stride = num_sets * block_size  # 2048
    A = 0x100
    B = A + same_set_stride
    C = B + same_set_stride

    expect(c.get_set_index(A) == c.get_set_index(B) == c.get_set_index(C),
           f"A,B,C mapeiam para o mesmo conjunto ({set_idx})")

    c.reset_state()
    c.access(A)   # miss, A é MRU
    c.access(B)   # miss, B é MRU, A é LRU
    c.access(A)   # hit, A volta para MRU
    expect(c.hits == 1, "A volta para MRU após hit")
    c.access(C)   # miss; deve despejar B (LRU), não A
    expect(c.find_way(set_idx, c.get_tag(A)) >= 0,
           "LRU preserva A após inserir C (vítima foi B)")
    expect(c.find_way(set_idx, c.get_tag(B)) == -1,
           "LRU despejou B (LRU correto)")


# ---------------------------- 3. DRRIP basic ---------------------------------

def test_drrip_long_vs_distant() -> None:
    """Verifica que blocos inseridos com RRPV=long (2) são preferidos sobre
    distant (3) já presentes, exatamente como no artigo (Fig. 3c)."""
    # 4 vias, força via política SRRIP pura para previsibilidade
    c = DRRIPCache("L1D", 256, 32, 4, policy="SRRIP")
    c.reset_state()

    # Após reset_state(), todas as linhas estão inválidas; o find_invalid_way
    # vai escolhê-las primeiro, então a primeira inserção não exercita victim.
    # Vamos popular o conjunto e então forçar uma substituição.
    set_idx_addr = 0  # set 0
    base = 0x0
    block = 32
    num_sets = c.num_sets
    stride = num_sets * block  # bloco em set 0 a cada `stride`
    addrs = [base + i * stride for i in range(4)]

    # Insere 4 blocos com SRRIP -> todos com RRPV = LONG_RRPV = 2
    for a in addrs:
        c.access(a)
    expect(c.misses == 4, "4 misses compulsórios")
    for line in c.sets[0]:
        expect(line.rrpv == c.LONG_RRPV,
               f"inserção SRRIP coloca RRPV=LONG ({c.LONG_RRPV}); obtido {line.rrpv}")

    # Agora insere um 5º bloco - deve ocorrer aging até RRPV=MAX
    # e então alguma vítima é escolhida.
    new_addr = base + 4 * stride
    c.access(new_addr)
    expect(c.misses == 5, "5º acesso é miss e dispara seleção de vítima")

    # Após a seleção, o bloco recém-inserido tem RRPV=LONG (=2)
    # e os outros 3 que sobreviveram têm RRPV=MAX (porque sofreram aging).
    rrpvs = sorted(line.rrpv for line in c.sets[0])
    expect(rrpvs.count(c.LONG_RRPV) == 1 and rrpvs.count(c.MAX_RRPV) == 3,
           f"Após inserção: 1 LONG + 3 DISTANT; RRPVs={rrpvs}")


def test_drrip_hit_promotes_to_zero() -> None:
    c = DRRIPCache("L1D", 256, 32, 4, policy="SRRIP")
    c.reset_state()
    c.access(0x0)                    # miss, RRPV=2
    line_idx = c.find_way(c.get_set_index(0), c.get_tag(0))
    assert line_idx >= 0
    expect(c.sets[0][line_idx].rrpv == c.LONG_RRPV, "após miss: RRPV=LONG")
    c.access(0x0)                    # hit -> HP rebaixa RRPV para 0
    expect(c.sets[0][line_idx].rrpv == 0, "após hit: RRPV=0 (HP)")


def test_drrip_overhead_smaller_than_lru() -> None:
    """Confirma o resultado central do artigo: para associatividade >= 8,
    DRRIP usa MENOS bits de metadados de política que LRU. Em assoc=4 elas
    se equivalem em bits/conjunto (4*2 == 4*log2(4)); o PSEL global do
    DRRIP adiciona uma constante fixa que se torna desprezível em caches
    grandes."""
    for assoc in (8, 16):
        lru = LRUCache("L2", 32 * 1024, 64, assoc)
        drrip = DRRIPCache("L2", 32 * 1024, 64, assoc, policy="DRRIP")
        # Bits comuns (tag + valid) cancelam-se; isolamos a parcela de política:
        tag_bits = 32 - lru.offset_bits - lru.index_bits
        common = lru.num_sets * assoc * (1 + tag_bits)
        lru_policy_bits = lru.storage_overhead_bits() - common
        drrip_policy_bits = drrip.storage_overhead_bits() - common
        ratio = lru_policy_bits / drrip_policy_bits
        expect(drrip_policy_bits < lru_policy_bits,
               f"assoc={assoc}: DRRIP metadados {drrip_policy_bits}b "
               f"< LRU {lru_policy_bits}b (LRU/DRRIP ≈ {ratio:.2f}x)")


# ---------------------------- 4. equivalência sob acessos triviais -----------

def test_drrip_lru_compulsory_misses_match() -> None:
    """Para uma sequência sem repetições (working set < cache), todas as
    políticas devem ter o mesmo número de misses compulsórios."""
    lru = LRUCache("L2", 32 * 1024, 64, 8)
    drrip = DRRIPCache("L2", 32 * 1024, 64, 8, policy="DRRIP")
    addrs = [i * 64 for i in range(100)]   # 100 blocos distintos (cabem em 32KB)
    for a in addrs:
        lru.access(a)
        drrip.access(a)
    expect(lru.misses == 100 == drrip.misses,
           "ambos têm exatamente 100 misses compulsórios para 100 blocos novos")
    # Segunda passada: todos devem ser hits
    for a in addrs:
        lru.access(a)
        drrip.access(a)
    expect(lru.hits == 100 and drrip.hits == 100,
           "segunda passada: 100 hits cada (working set cabe na cache)")


# ---------------------------- runner ------------------------------------------

def run_all() -> int:
    tests = [
        test_address_layout,
        test_lru_basic_hit_miss,
        test_drrip_long_vs_distant,
        test_drrip_hit_promotes_to_zero,
        test_drrip_overhead_smaller_than_lru,
        test_drrip_lru_compulsory_misses_match,
    ]
    failed = 0
    for t in tests:
        print(f"\n--- {t.__name__} ---")
        try:
            t()
        except AssertionError:
            failed += 1
    print()
    print(f"==== {len(tests)-failed}/{len(tests)} testes OK ====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run_all())
