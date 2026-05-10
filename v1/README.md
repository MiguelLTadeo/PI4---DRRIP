# Caches Inteligentes em RISC-V (FPGA): DRRIP

**Projeto Integrador IV — 2026/1**
**Algoritmo: DRRIP (Dynamic Re-Reference Interval Prediction)**

## Status atual

- [x] Modelagem Python (cache + DRRIP + LRU + benchmarks)
- [x] Validação de Hit Rate em traces sintéticos
- [x] HDL inicial: cache_drrip.v, cache_lru.v, memory_hierarchy.v
- [x] Testbench Verilog inicial
- [x] Benchmarks bare-metal em C
- [ ] Integração com core RISC-V (aguardando download)
- [ ] Síntese no Quartus (Cyclone III EP3C25F324C6)
- [ ] Captura de métricas reais em FPGA
- [ ] Relatório final

## Estrutura

```
/docs        Relatório (PDF) e diagramas
/modelagem   Modelo Python (golden reference) - Sprints 1-4
/rtl
  /cache         Caches L1 e L2 com DRRIP/LRU em Verilog
  /riscv_core    (a preencher após download do core)
/sim         Testbenches e scripts ModelSim
/software    Benchmarks em C bare-metal RV32I
/synth       Relatórios Quartus (utilização, timing)
```

## Como rodar a modelagem

```bash
cd modelagem
python3 run_experiments.py            # roda todos benchmarks/configs
python3 run_experiments.py --csv      # exporta CSV detalhado
python3 run_experiments.py --quick    # smoke test (1 bench, 1 config)
```

Saída esperada (resumo): comparação LRU vs DRRIP em hit rate global por
configuração de cache.

## Como simular o RTL (após instalar ModelSim/Icarus)

```bash
cd sim
iverilog -o tb_drrip ../rtl/cache/cache_drrip.v tb_cache_drrip.v
vvp tb_drrip
```

## Resultados preliminares (modelo Python, traces sintéticos)

| Config (L1/L2) | Benchmark      | LRU hit% | DRRIP hit% | Δ (pp) |
|----------------|----------------|----------|------------|--------|
| 4KB-2w / 32KB-8w  | streaming      | 97.60 | 97.48 | -0.12  |
| 4KB-2w / 32KB-8w  | matrix_conv    | 67.95 | 95.85 | +27.90 |
| 4KB-2w / 32KB-8w  | linked_list    | 96.55 | 96.20 | -0.34  |
| 4KB-2w / 32KB-8w  | pattern_search | 99.88 | 99.88 | +0.00  |
| 8KB-4w / 128KB-16w| matrix_conv    | 80.59 | 95.85 | +15.26 |

**Caveat**: traces sintéticos. Números finais deverão ser obtidos com traces
reais via QtRVSim ou Gem5 antes da entrega do relatório.

## Decisões de projeto principais

1. **DRRIP com aging multi-ciclo (FSM)** ao invés de combinacional,
   priorizando Fmax sobre latência. Custo: até 3 ciclos extras no miss.
2. **PSEL de 10 bits** com início em 512 (paper).
3. **Set dueling determinístico** via comparação de bits do índice
   (constituency = 32 sets), evitando hash custoso.
4. **BRRIP bimodal por contador determinístico (1/32)** ao invés de LFSR,
   reduzindo área a custo desprezível em hit rate.
5. **Baseline com Tree-PLRU** (não LRU exato) para comparação justa,
   alinhado à prática industrial.

## Roadmap restante (Sprints 9–12)

- Substituir traces sintéticos por execução real em QtRVSim/Gem5
- Integrar caches no core RISC-V (assim que disponível)
- Adicionar contadores hit/miss expostos como CSRs customizados
- Síntese e timing closure no Quartus
- Coletar métricas finais (LEs, BRAMs, Fmax) e preencher Apêndice B
- Escrever relatório (10 págs)

## Equipe

- (preencher)
- (preencher)

## Referências principais

- Jaleel, A., Theobald, K., Steely, S., Emer, J. *High Performance Cache
  Replacement Using Re-Reference Interval Prediction (RRIP)*, ISCA 2010.
