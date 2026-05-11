"""
Geradores de trace de memória para os benchmarks do Apêndice A da
especificação.

Cada benchmark é uma função geradora que produz uma sequência de
endereços de DATA a serem acessados. Mantemos a mesma estrutura de
acesso do código C original, mas escalonável (parâmetros configuráveis
de tamanho) para que possamos rodar em tempo razoável durante a
modelagem.

Convenção de bases de endereçamento (arbitrária, mas alinhada a regiões
grandes para minimizar conflitos de índice entre estruturas distintas):
    0x10000000 .. estrutura primária
    0x20000000 .. estrutura secundária
    0x30000000 .. variável "hot"
"""

from __future__ import annotations

import random
from typing import Iterator


# ----- ESCALAS PADRÃO ----------------------------------------------------
# Mantemos as proporções da especificação (working set ~ 2x L2) mas
# parametrizáveis para que a modelagem rode rápido.

DEFAULT_L2_BYTES = 32 * 1024            # 32 KB, a menor L2 da especificação


# =========================================================================
# 1. STREAMING + HOTSET
# =========================================================================

def streaming_hotset(
    array_size_bytes: int = 2 * DEFAULT_L2_BYTES,
    iterations: int = 5,
    elem_size: int = 4,
    array_base: int = 0x10000000,
    hot_addr: int = 0x30000000,
) -> Iterator[int]:
    """Streaming + HotSet (antagonista ao LRU).

    Replica o run_streaming() do Apêndice A:
        for it in 0..iterations:
            for i in 0..N:
                array[i] += i              -> 1 read + 1 write
                if i % 64 == 0:
                    *hot_data += array[i]  -> 1 read + 1 write em 'hot'
    """
    n_elems = array_size_bytes // elem_size
    for _ in range(iterations):
        for i in range(n_elems):
            addr = array_base + i * elem_size
            yield addr           # leitura array[i]
            yield addr           # escrita array[i]
            if i % 64 == 0:
                yield hot_addr   # leitura hot
                yield hot_addr   # escrita hot


# =========================================================================
# 2. MATRIX CONVOLUTION (reuso temporal em janela vertical)
# =========================================================================

def matrix_convolution(
    width: int = 128,
    height: int = 128,
    elem_size: int = 4,
    img_base: int = 0x10000000,
    out_base: int = 0x20000000,
) -> Iterator[int]:
    """Convolução 2D vertical (janela 3x1):
        out[y,x] = img[y-1,x] + img[y,x] + img[y+1,x]

    Apresenta forte reuso temporal entre linhas adjacentes - uma linha
    é lida nas iterações y-1, y e y+1, fornecendo grande oportunidade
    de cache hit se as 3 linhas couberem na cache (L1 ou L2).
    """
    row_bytes = width * elem_size
    for y in range(1, height - 1):
        row_top = img_base + (y - 1) * row_bytes
        row_mid = img_base + y * row_bytes
        row_bot = img_base + (y + 1) * row_bytes
        out_row = out_base + y * row_bytes
        for x in range(1, width - 1):
            xb = x * elem_size
            yield row_top + xb
            yield row_mid + xb
            yield row_bot + xb
            yield out_row + xb


# =========================================================================
# 3. LINKED LIST TRAVERSAL (pointer chasing)
# =========================================================================

def linked_list(
    n_nodes: int = 8000,
    iterations: int = 5,
    node_size: int = 16,       # struct { int data; struct Node *next; } com padding
    nodes_base: int = 0x10000000,
    seed: int = 123,
    randomize_order: bool = True,
) -> Iterator[int]:
    """Travessia de lista encadeada. Cada nó tem `data` e `next`.

    Se `randomize_order=True` os ponteiros 'next' formam um ciclo embaralhado,
    o que reproduz o caso difícil de pointer chasing em que LRU/qualquer
    política racional pode ter dificuldade quando o working set excede a cache.

    Acessos por nó visitado:
        - read  data        (nodes_base + idx*node_size + 0)
        - write data        (mesma palavra)
        - read  next        (nodes_base + idx*node_size + 8)
    """
    rng = random.Random(seed)
    order = list(range(n_nodes))
    if randomize_order:
        rng.shuffle(order)
    next_of = {order[i]: order[(i + 1) % n_nodes] for i in range(n_nodes)}

    curr = order[0]
    total_visits = n_nodes * iterations
    for _ in range(total_visits):
        base = nodes_base + curr * node_size
        yield base               # leitura  data
        yield base               # escrita  data
        yield base + 8           # leitura  next
        curr = next_of[curr]


# =========================================================================
# 4. PATTERN SEARCH (estresse de L2 unificada)
# =========================================================================

def pattern_search(
    size: int = DEFAULT_L2_BYTES,
    window: int = 64,
    blob_base: int = 0x10000000,
) -> Iterator[int]:
    """Busca por padrão dentro de uma janela:
        for i in [window, size):
            for j in [1, window):
                if blob[i] == blob[i-j]:
                    blob[i]++
                    break
    No pior caso (sem match), acessa blob[i] uma vez e blob[i-j] para j=1..63.

    O acesso é altamente local mas ainda pressiona a L2 quando o blob >> L1.
    """
    for i in range(window, size):
        # No pior caso (sem match) percorremos toda a janela
        for j in range(1, window):
            yield blob_base + i
            yield blob_base + (i - j)
        # Modela o blob[i]++ em caso de "match" (ocorrência heurística simples)
        if (i & 0x3F) == 0:
            yield blob_base + i


# =========================================================================
# 5. MIXED ACCESS PATTERN (Fig. 1d do artigo Jaleel et al. 2010)
# =========================================================================
#
# Este benchmark NÃO está na especificação original mas é incluído como
# carga complementar para validar especificamente a propriedade que
# motivou o DRRIP: preservar um working-set frequente diante de "scans"
# que invadem a cache.
#
# Padrão:  [ (a_1..a_k)^A   (b_1..b_m)   ]^N
#
#   - working set (a_1..a_k): k blocos que CABEM na cache (referência
#     recente, alta localidade temporal). LRU iria mantê-los — se não
#     houvesse o scan.
#   - scan (b_1..b_m): m >> capacidade da cache, blocos vistos UMA vez
#     cada. LRU os trata como MRU e expulsa todo o working set; quando
#     o working set retorna, dá 100% de miss.
#   - DRRIP: insere blocos do scan com RRPV=long (ou distant em BRRIP),
#     preservando o working set. Quando o working set retorna, dá hits.
# =========================================================================

def mixed_access_pattern(
    ws_blocks: int = 64,          # working set: 64 blocos = 2KB com bloco 32B (cabe em L1 4KB)
    scan_blocks: int = 2048,      # scan: 2048 blocos = 64KB com bloco 32B (>> L1)
    ws_repeats: int = 8,          # quantas vezes o working set roda antes do scan
    outer_iters: int = 5,         # quantas vezes o padrão (ws + scan) repete
    block_size: int = 32,         # bloco da L1 (a granularidade que importa para hit/miss)
    ws_base: int = 0x10000000,
    scan_base: int = 0x40000000,
) -> Iterator[int]:
    ws_addrs = [ws_base + i * block_size for i in range(ws_blocks)]
    scan_addrs = [scan_base + i * block_size for i in range(scan_blocks)]

    for _ in range(outer_iters):
        # Working set: A repetições
        for _ in range(ws_repeats):
            for a in ws_addrs:
                yield a
        # Scan: visita única
        for b in scan_addrs:
            yield b


# =========================================================================
# REGISTRO DOS BENCHMARKS
# =========================================================================

BENCHMARKS = {
    "streaming_hotset": streaming_hotset,
    "matrix_conv":      matrix_convolution,
    "linked_list":      linked_list,
    "pattern_search":   pattern_search,
    "mixed_access":     mixed_access_pattern,
}


def all_benchmark_factories():
    """Devolve dict(name -> callable) com configurações padrão de modelagem."""
    return BENCHMARKS
