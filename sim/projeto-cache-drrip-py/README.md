# Projeto Integrador IV — DRRIP vs LRU (modelagem Python)

Modelagem em Python do algoritmo de substituição de cache **DRRIP**
(Dynamic Re-Reference Interval Prediction, Jaleel *et al.*, ISCA 2010),
comparado contra **LRU** verdadeiro, cobrindo as **Semanas 1–4** do
cronograma da disciplina (UNIPAMPA).

## Estrutura

```
projeto-cache-drrip/
├── model/                          # Núcleo da modelagem
│   ├── cache.py                    # Classe base Cache (set-associativa)
│   ├── lru.py                      # LRU verdadeiro
│   ├── drrip.py                    # DRRIP (SRRIP + BRRIP + Set Dueling)
│   ├── memory_hierarchy.py         # L1D + L2 + AMAT
│   ├── benchmarks.py               # 5 geradores de trace
│   └── tests.py                    # 6 testes unitários
├── docs/
│   └── modelagem.md                # RELATÓRIO TÉCNICO (semanas 1-4)
├── results/                        # Saída dos experimentos
│   ├── hit_rates.csv               # Resultado bruto
│   ├── summary.csv                 # LRU vs DRRIP por config/benchmark
│   ├── overhead.csv                # Bits de SRAM (LRU vs DRRIP)
│   └── plots/*.png                 # 5 gráficos
├── software/                       # (vazio - será preenchido nas próx semanas)
├── plot_results.py                 # Geração dos gráficos
└── run_experiments.py              # Script principal
```

## Como rodar

```bash
# 1. testes unitários (~1 s)
python -m model.tests

# 2. experimentos completos (~45 s, varre 3 configs × 5 benchmarks × 2 políticas)
python run_experiments.py

# 3. gráficos (CSVs em results/ devem existir)
python plot_results.py
```

Não há dependências externas além da biblioteca padrão e do `matplotlib`
(este último apenas para `plot_results.py`).

## Resultados principais

Configurações testadas (Seção 4 da especificação):

| Config | L1D | L2 |
|---|---|---|
| A | 4 KB / 32 B / 2 vias | 32 KB / 64 B / 8 vias |
| B | 4 KB / 32 B / 4 vias | 64 KB / 64 B / 8 vias |
| C | 8 KB / 32 B / 4 vias | 128 KB / 64 B / 16 vias |

Variação média do DRRIP sobre LRU (média entre configs):

| Benchmark | ΔL1 hit (pp) | ΔL2 hit (pp) | AMAT speedup |
|---|---|---|---|
| streaming_hotset | +0,00 | +0,00 | +0,00 % |
| matrix_conv | +0,00 | +0,00 | +0,00 % |
| linked_list | −0,00 | +0,27 | +0,36 % |
| pattern_search | +0,00 | +0,00 | +0,00 % |
| **mixed_access** (Fig.1d, Jaleel) | **+5,15** | −1,08 | **+8,92 %** |

E **overhead reduzido**: em L2 16-vias o DRRIP gasta 32 bits/conjunto
contra 64 do LRU (−50 % de bits de estado de política).

O relatório completo, com a discussão de cada benchmark e da implementação,
está em [`docs/modelagem.md`](docs/modelagem.md).

## Referências

- Jaleel, A. *et al.* **"High Performance Cache Replacement Using Re-reference Interval Prediction (RRIP)."** *ISCA 2010.*
- Qureshi, M. K. *et al.* **"Adaptive Insertion Policies for High Performance Caching."** *ISCA 2007.* (Set Dueling)
- Especificação do Projeto Integrador IV — UNIPAMPA, 2025.
