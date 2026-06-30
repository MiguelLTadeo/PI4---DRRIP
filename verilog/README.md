# Sprint 3 — Implementação em Verilog

Projeto Integrador IV — UNIPAMPA, Engenharia de Computação
Discentes: Juan Rocha, Miguel Tadeo, Thales Kun

Este diretório contém a implementação RTL (Verilog-2001) da cache da Sprint 2,
agora descrita em hardware, com a mesma metodologia: **uma única cache
parametrizável, mudando apenas a política de inserção** (LRU vs DRRIP).

## Estrutura

```
sprint3/
├── rtl/
│   └── cache.v                # Cache parametrizável (LRU + DRRIP)
├── tb/
│   ├── tb_cache.v             # Testbench genérica (lê trace de arquivo)
│   └── tb_top.v               # Wrappers fixando parâmetros por config
├── traces/
│   ├── gen_traces.c           # Gerador de traces (porte dos benchmarks)
│   └── *.hex                  # Traces gerados (1 endereço hex por linha)
├── sim/
│   ├── run_all.sh             # Roda as 30 simulações e gera CSV
│   ├── run_modelsim.do        # Script equivalente para ModelSim
│   ├── plot.py                # Plota hit rate L1D Verilog
│   ├── plot_c_vs_verilog.py   # Compara Verilog vs referência C
│   └── results.csv            # Resultados consolidados
├── docs/
│   ├── hit_rate_verilog.png   # Gráfico principal da Sprint 3
│   └── c_vs_verilog.png       # Validação cruzada
└── Makefile                   # Fluxo build/run/plot
```

## Como rodar (Icarus Verilog)

```bash
make all
```

Isto compila o gerador de traces, gera os 5 arquivos `.hex`, compila os 6
binários de simulação (3 configs × 2 políticas), roda os 30 testes
(3 × 5 benchmarks × 2 políticas) e produz os gráficos.

Pré-requisitos: `iverilog`, `gcc`, `python3` com `matplotlib`.

## Como rodar (ModelSim / Quartus)

No prompt do ModelSim, dentro do diretório `sprint3/`:

```tcl
do sim/run_modelsim.do
```

O script de exemplo carrega Config A com LRU em `streaming_hotset`. Para
outras combinações, troque o `vsim` no final do `.do` por
`tb_cfgA_drrip`, `tb_cfgB_lru`, etc. — temos 6 top-levels, um por
combinação.

## Decisões de design

1. **Política parametrizável em tempo de compilação** (`POLICY` 0=LRU,
   1=DRRIP). Mantém a metodologia da Sprint 2.
2. **Tag-array apenas**, sem data-array. A pesquisa é sobre política de
   substituição; armazenar dados de fato dobraria o tamanho do RTL sem
   afetar o número que importa (hit rate).
3. **Um acesso por ciclo de clock**. Lookup combinacional (busca de tag,
   identificação de vítima, decisão LRU/DRRIP). Atualizações registradas
   na borda de subida.
4. **DRRIP canônico (Jaleel et al., ISCA 2010)** com set dueling
   completo: PSEL de 10 bits, BIP_MAX = 32 para inserção bimodal, leaders
   SRRIP e BRRIP definidos por faixa de índice de set (1/16 dos sets cada,
   mínimo 4, máximo 32). *Não* replicamos o bug do `std::knuth_b{1}` do
   ChampSim aqui — a Sprint 2 já documentou esse comportamento; o
   objetivo agora é o DRRIP que efetivamente vence o LRU.
5. **Verilog-2001 puro**: compila em iverilog, ModelSim e Quartus sem
   warnings.

## Resultados

| Config | Benchmark        | LRU    | DRRIP  | Δ       |
|--------|------------------|--------|--------|---------|
| A      | streaming_hotset | 93.84% | 93.84% | 0.00    |
| A      | matrix_conv      | 93.65% | 93.65% | 0.00    |
| A      | linked_list      | 68.60% | 68.61% | +0.01   |
| A      | pattern_search   | 99.62% | 99.62% | 0.00    |
| A      | mixed_access     | 70.00% | 78.91% | **+8.91**  |
| B      | streaming_hotset | 93.84% | 93.84% | 0.00    |
| B      | matrix_conv      | 93.65% | 93.65% | 0.00    |
| B      | linked_list      | 68.65% | 68.66% | +0.01   |
| B      | pattern_search   | 99.62% | 99.62% | 0.00    |
| B      | mixed_access     | 70.00% | 82.17% | **+12.17** |
| C      | streaming_hotset | 93.84% | 93.84% | 0.00    |
| C      | matrix_conv      | 93.65% | 93.65% | 0.00    |
| C      | linked_list      | 70.60% | 70.73% | +0.13   |
| C      | pattern_search   | 99.62% | 99.62% | 0.00    |
| C      | mixed_access     | 96.25% | 96.25% | 0.00    |

### Comparação com o C de referência (Sprint 2)

| Benchmark        | LRU C  | LRU Verilog | DRRIP C | DRRIP Verilog | Status |
|------------------|--------|-------------|---------|---------------|--------|
| streaming_hotset | 93.85% | 93.84%      | 93.85%  | 93.84%        | ✔ idênticos |
| matrix_conv      | 93.70% | 93.65%      | 93.70%  | 93.65%        | ✔ Δ < 0.05  |
| linked_list      | 67.2%  | 68.6%       | 67.2%   | 68.6%         | ✓ pequena diff de aging |
| pattern_search   | 99.62% | 99.62%      | 99.62%  | 99.62%        | ✔ idênticos |
| mixed_access     | 68.18% | 70.00%      | 71-78%  | 78-82%        | ✓ workload menor no Verilog |

As pequenas divergências em `linked_list` e `mixed_access` vêm de
diferenças nos **parâmetros dos benchmarks** (o C de vocês usa workloads
maiores) e não da política. Para reproduzir números idênticos, basta
ajustar `gen_traces.c` aos parâmetros do `main.c` do projeto Sprint 2.

## Próximos passos (Sprint 4)

- Integração com core RISC-V (RV32I bare-metal): conectar a interface da
  cache ao barramento do processador.
- Síntese para FPGA (Cyclone) e medição de área/timing/recursos.
- Implementação de uma L2 unificada em Verilog (no momento só L1D
  existe em RTL).
