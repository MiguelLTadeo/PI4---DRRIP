# Projeto Integrador IV — Caches Inteligentes em RISC-V (FPGA)

**Disciplina:** Projeto Integrador IV — UNIPAMPA 2026/1  
**Algoritmo:** DRRIP (*Dynamic Re-Reference Interval Prediction*, Jaleel *et al.*, ISCA 2010)  
**Aluno:** Miguel L. Tadeo

---

## Estrutura do Repositório

```
PI4---DRRIP/
├── docs/           Relatório final (PDF) e diagramas de arquitetura
├── rtl/            Código HDL (Verilog): subpastas cache/ e riscv_core/
├── sim/
│   ├── projeto-cache-c/         Simulador C — DRRIP vs LRU (modelagem Semanas 1–4)
│   └── projeto-cache-drrip-py/  Modelagem Python inicial (referência)
├── software/       Código-fonte dos benchmarks em C (Apêndice A da especificação)
├── synth/          Relatórios de síntese (utilização e timing — Quartus)
└── README.md       Este arquivo
```

---

## Como Rodar o Simulador C

```bash
cd sim/projeto-cache-c

# Compilar
make

# Executar simulação (gera results/hit_rates.csv e results/overhead.csv)
make run

# Gerar gráficos (requer Python 3 + matplotlib)
make plots

# Limpar artefatos
make clean
```

---

## Configurações de Cache Testadas

| Config | L1D (Dados) | L2 (Unificada) |
|--------|-------------|----------------|
| A | 4 KB / 32 B / 2 vias | 32 KB / 64 B / 8 vias |
| B | 4 KB / 32 B / 4 vias | 64 KB / 64 B / 8 vias |
| C | 8 KB / 32 B / 4 vias | 128 KB / 64 B / 16 vias |

---

## Tabela Resumo de Resultados — Taxa de Acerto L1 (%)

Benchmark mais discriminante: **mixed\_access** (working-set + scan invasivo).  
Latências: L1=1 ciclo, L2=10 ciclos, Memória=100 ciclos.  
AMAT = 1 + (1−h_L1)×(10 + (1−h_L2)×100).

| Config | Política | L1 hit (%) | L2 hit (%) | AMAT (ciclos) | Ganho vs LRU |
|--------|----------|-----------|-----------|---------------|--------------|
| A | LRU | 68,18 | 95,00 | 5,77 | — |
| A | DRRIP-Jaleel | 69,20 | 94,83 | 5,67 | +1,02 pp |
| A | DRRIP-ChampSim | 69,46 | 94,79 | 5,64 | +1,28 pp |
| B | LRU | 68,18 | 95,00 | 5,77 | — |
| B | DRRIP-Jaleel | 69,72 | 94,75 | 5,62 | +1,55 pp |
| B | DRRIP-ChampSim | 70,33 | 94,64 | 5,56 | +2,15 pp |
| C | LRU | 68,18 | 95,00 | 5,77 | — |
| C | **DRRIP-Jaleel** | **74,32** | 93,81 | **5,16** | **+6,14 pp** |
| C | **DRRIP-ChampSim** | **74,82** | 93,68 | **5,11** | **+6,64 pp** |

> Config C (L2 128 KB / 16 vias) é onde o DRRIP mais se beneficia: o Set Dueling detecta
> o padrão de thrashing do mixed\_access e ativa BRRIP, preservando o working-set.

### Benchmark de Validação (cache mínima: 128B / 16B bloco / 2 vias)

Trace de 8 acessos que expõe BRRIP × SRRIP × LRU no cenário warm-up + scan:

| Política | L1 hit (%) | AMAT (ciclos) |
|----------|-----------|---------------|
| LRU | 25,00 | 58,50 |
| DRRIP-Jaleel (SRRIP) | 25,00 | 58,50 |
| **DRRIP-ChampSim (BIP)** | **37,50** | **57,25** |

O DRRIP-ChampSim insere o scan com RRPV=3 (distant), preservando o bloco B no
working-set — exatamente o comportamento da Figura 3c do paper de Jaleel.

---

## Overhead de Metadados por Conjunto

| Política | bits/conjunto (2-vias) | bits/conjunto (16-vias) |
|----------|----------------------|------------------------|
| LRU | 2 | 64 |
| DRRIP | 4 | 32 |

DRRIP usa apenas **2 bits por linha** (RRPV de 2 bits), contra `n·⌈log₂(n)⌉` do LRU.  
Em 16 vias, DRRIP consome **50 % menos bits** de estado de política que LRU.

---

## Referências

- Jaleel, A. *et al.* **"High Performance Cache Replacement Using Re-reference Interval Prediction (RRIP)."** *ISCA 2010.*
- Qureshi, M. K. *et al.* **"Adaptive Insertion Policies for High Performance Caching."** *ISCA 2007.* (Set Dueling / DIP)
- ChampSim — *Cache Hierarchy and Memory Performance Simulator.* (portado para C)
- Especificação do Projeto Integrador IV — UNIPAMPA, 2026/1.
