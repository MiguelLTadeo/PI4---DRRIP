# Projeto Cache Replacement em C

Implementa três políticas de substituição de cache, com hierarquia L1+L2:

- **LRU** (`src/lru.c`) — baseline clássico
- **DRRIP-Jaleel** (`src/drrip_jaleel.c`) — DRRIP do paper Jaleel et al. (ISCA 2010), com adaptações pra caches pequenas de FPGA
- **DRRIP-ChampSim** (`src/drrip_champsim.c`) — porte literal do `drrip.cc` do ChampSim, preservando o bug do `knuth_b` sem módulo

## Estrutura

```
projeto-cache-c/
├── src/
│   ├── cache.h, cache.c              # geometria comum
│   ├── lru.h, lru.c                  # LRU
│   ├── drrip_jaleel.h, drrip_jaleel.c    # DRRIP do paper
│   ├── drrip_champsim.h, drrip_champsim.c # DRRIP do ChampSim fiel
│   ├── benchmarks.h, benchmarks.c    # 5 geradores de trace
│   └── main.c                        # driver experimental
├── plot_results.py                    # gráficos a partir do CSV
├── Makefile
├── build/                             # objetos compilados
├── results/                           # CSVs gerados
│   ├── hit_rates.csv
│   └── overhead.csv
└── plots/                             # gráficos PNG
    ├── 01_hit_rate_l1.png
    ├── 02_hit_rate_l2.png
    ├── 03_amat.png
    ├── 04_overhead.png
    └── 05_mixed_access_zoom.png
```

## Como rodar

Requisitos: `gcc`, `make`, `python3` com `matplotlib`.

```bash
make            # compila build/sim
make run        # roda simulação e gera CSVs em results/
make plots      # roda simulação E gera gráficos em plots/
make clean      # limpa tudo
```

## Configurações testadas

| Config | L1D | L2 |
|---|---|---|
| A | 4 KB / 32 B / 2 vias | 32 KB / 64 B / 8 vias |
| B | 4 KB / 32 B / 4 vias | 64 KB / 64 B / 8 vias |
| C | 8 KB / 32 B / 4 vias | 128 KB / 64 B / 16 vias |

## Benchmarks

1. **streaming_hotset** — varredura linear + variável quente periódica
2. **matrix_conv** — convolução vertical 3×1 em matriz 128×128
3. **linked_list** — pointer chasing com ordem embaralhada
4. **pattern_search** — janela deslizante de 32 elementos
5. **mixed_access** — *working set + scan invasivo* (Fig. 1d do paper)

## Métricas

- L1 e L2 hit rate
- AMAT = 1 + (1−h_L1)·(10 + (1−h_L2)·100) ciclos
- Bits de SRAM por política (tag + valid + RRPV/age + extras)
