"""
traces.py
=========
Geradores de traces de acesso a memoria que reproduzem os 4 benchmarks
do Apendice A da especificacao.

Cada gerador retorna um iteravel de tuplas (addr, kind), onde:
  kind in {'I','R','W'}.

IMPORTANTE: estes traces sao APROXIMACOES do comportamento dos benchmarks
em C. A versao final precisa rodar os benchmarks em C compilados para
RV32I e capturar traces REAIS (via QtRVSim ou Gem5). Estes geradores sao
suficientes para Sprints 1-4 (modelagem) e ja revelam tendencias claras.

Layout de memoria assumido (consistente entre traces):
  CODE_BASE = 0x00400000   (instrucoes)
  HEAP_BASE = 0x10000000   (big_array, out_array, blob)
  STACK_BASE= 0x7FFF0000   (variaveis locais, hot_data)

Para cada operacao C, modelamos:
  - acessos de instrucao (fetch do PC) ao codigo do loop
  - acessos de dado (R/W) aos arrays
"""

import random
from typing import Iterator, Tuple

# Endereco base
CODE_BASE  = 0x00400000
HEAP_BASE  = 0x10000000
STACK_BASE = 0x7FFF0000

# Tamanho assumido dos arrays (mesmo da macro do Apendice A)
L2_SIZE_BYTES = 128 * 1024
ARRAY_SIZE = L2_SIZE_BYTES * 2 // 4   # ARRAY_SIZE em ints (4 bytes)


def _fetch_burst(pc_base: int, n_instr: int) -> Iterator[Tuple[int, str]]:
    """Gera n_instr instructions a partir de pc_base (4 bytes cada)."""
    for i in range(n_instr):
        yield (pc_base + 4 * i, 'I')


# ---------------------------------------------------------------------------
# Benchmark 1: Streaming + HotSet (antagonista ao LRU)
# ---------------------------------------------------------------------------
# Para cada iteracao do loop interno (i=0..ARRAY_SIZE-1):
#   - le array[i], escreve array[i] (~4 instrucoes assembly p/ corpo)
#   - se i % 64 == 0: le hot_data, soma, escreve hot_data
# O loop externo roda 10 vezes. ARRAY_SIZE = 64K ints = 256 KB
# (2x maior que L2 max), entao streaming PURO destroi LRU.
# Mantemos numero de iteracoes reduzido para o trace ser tratavel.

def trace_streaming(outer_iters: int = 2,
                    array_words: int = ARRAY_SIZE // 16) -> Iterator[Tuple[int, str]]:
    """
    Versao reduzida (o ARRAY_SIZE original gera ~50M acessos; usamos /16).
    Mesmo padrao, escala suficiente para evidenciar comportamento.
    """
    pc_loop = CODE_BASE          # instr do loop principal
    pc_hot  = CODE_BASE + 0x40   # instr do bloco "if i%64==0"
    array_base = HEAP_BASE
    hot_addr   = STACK_BASE      # variavel hot_val (volatile int)

    for _ in range(outer_iters):
        for i in range(array_words):
            # Fetch das ~4 instrucoes do corpo do loop interno
            yield from _fetch_burst(pc_loop, 4)
            # array[i] += i  -> read + write em array[i]
            addr = array_base + 4 * i
            yield (addr, 'R')
            yield (addr, 'W')
            # if (i % 64 == 0)
            if (i & 63) == 0:
                yield from _fetch_burst(pc_hot, 3)
                yield (hot_addr, 'R')
                yield (addr, 'R')      # le array[i]
                yield (hot_addr, 'W')


# ---------------------------------------------------------------------------
# Benchmark 2: Matriz 2D - Convolucao (reuso em janela)
# ---------------------------------------------------------------------------
# out[y*W+x] = img[(y-1)*W+x] + img[y*W+x] + img[(y+1)*W+x]
# Reuso temporal moderado: linha y-1 vista 2 vezes no proximo passo.

def trace_matrix_conv(width: int = 128,
                      height: int = 128) -> Iterator[Tuple[int, str]]:
    pc = CODE_BASE + 0x100
    img_base = HEAP_BASE
    out_base = HEAP_BASE + width * height * 4

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            # ~5 instrucoes por iteracao (3 loads, 1 store, branch)
            yield from _fetch_burst(pc, 5)
            yield (img_base + ((y - 1) * width + x) * 4, 'R')
            yield (img_base + (y * width + x) * 4, 'R')
            yield (img_base + ((y + 1) * width + x) * 4, 'R')
            yield (out_base + (y * width + x) * 4, 'W')


# ---------------------------------------------------------------------------
# Benchmark 3: Linked List Traversal (pointer chasing)
# ---------------------------------------------------------------------------
# Lista circular de 2000 nos. Cada no tem int data + ponteiro next (8 bytes).
# 'count*50' iteracoes faz ~25 voltas completas (locality moderada se cabe
# na cache; thrashing se nao cabe).

def trace_linked_list(count: int = 2000,
                      iterations: int = 2000 * 5) -> Iterator[Tuple[int, str]]:
    pc = CODE_BASE + 0x200
    nodes_base = HEAP_BASE
    NODE_SIZE = 8  # int data + ptr next (RV32 -> 4+4)

    # Pre-computa enderecos dos nos. A ordem de travessia segue links;
    # como inicializado em 'for(i=0;i<1999;i++) nodes[i].next=&nodes[i+1]'
    # e 'nodes[1999].next=&nodes[0]', a ordem e' 0,1,2,...,count-1,0,1,...
    for k in range(iterations):
        idx = k % count
        node_addr = nodes_base + idx * NODE_SIZE
        yield from _fetch_burst(pc, 4)
        yield (node_addr,     'R')   # le data
        yield (node_addr,     'W')   # escreve data += i
        yield (node_addr + 4, 'R')   # le next


# ---------------------------------------------------------------------------
# Benchmark 4: Pattern Search (estresse de L2 unificada)
# ---------------------------------------------------------------------------
# Para i de 1024 ate size: para j de 1 ate 64: compara blob[i] com blob[i-j].
# Acessos densos com janela deslizante - bom reuso temporal de curto alcance.

def trace_pattern_search(size: int = L2_SIZE_BYTES // 2,
                         max_j: int = 64) -> Iterator[Tuple[int, str]]:
    pc = CODE_BASE + 0x300
    blob_base = HEAP_BASE
    # Reduzimos o tamanho efetivo para trace tratavel; mantem proporcao.
    for i in range(1024, size):
        yield from _fetch_burst(pc, 3)   # entrada do loop externo
        target = blob_base + i
        for j in range(1, max_j):
            yield from _fetch_burst(pc + 0x10, 4)
            yield (target,          'R')
            yield (blob_base + i - j, 'R')
            # No C original: 'if (blob[i] == blob[i-j]) {blob[i]++; break;}'
            # Modelamos o break heuristicamente em ~10% dos casos.
            if (i + j) % 11 == 0:
                yield (target, 'W')
                break


# ---------------------------------------------------------------------------
# Catalogo
# ---------------------------------------------------------------------------

BENCHMARKS = {
    'streaming':      trace_streaming,
    'matrix_conv':    trace_matrix_conv,
    'linked_list':    trace_linked_list,
    'pattern_search': trace_pattern_search,
}
