# Como rodar no Quartus + ModelSim (passo a passo)

Este guia é para a configuração que o professor pediu: Quartus Prime (com
ModelSim‑Intel FPGA Starter Edition que vem junto na instalação).

## Pré-requisitos

- **Quartus Prime Lite** (gratuito, baixe em intel.com) — vem com o
  ModelSim‑Intel FPGA Starter Edition.
- Caso o ModelSim não tenha vindo no instalador (depende da versão),
  instale `ModelSim‑Intel FPGA Edition` separadamente.

## Passo 1: simulação rápida em ModelSim (sem mexer no Quartus)

1. Descompacte o zip. Vamos chamar a pasta de `sprint3/`.
2. Abra o **ModelSim** (não o Quartus).
3. No prompt do ModelSim (a janela `Transcript`), digite:

   ```tcl
   cd C:/caminho/para/sprint3
   do sim/run_modelsim.do
   ```

   Ajuste o caminho. Use barras `/` mesmo no Windows.

4. O script compila tudo e roda **Config A com LRU em `streaming_hotset`**.
   A última linha da janela `Transcript` será algo como:

   ```
   RESULT cfg=A bench=? policy=LRU accesses=16640 hits=15615 misses=1025 hit_rate=0.9384
   ```

5. Para rodar **outra combinação**, abra `sim/run_modelsim.do` e troque
   na última `vsim`:
   - Top-level: `tb_cfgA_lru`, `tb_cfgA_drrip`, `tb_cfgB_lru`,
     `tb_cfgB_drrip`, `tb_cfgC_lru`, `tb_cfgC_drrip` (6 opções).
   - Trace: `+TRACE=traces/<nome>.hex` —
     `streaming_hotset`, `matrix_conv`, `linked_list`,
     `pattern_search` ou `mixed_access`.

   Salve o `.do` e rode `do sim/run_modelsim.do` de novo.

6. Para rodar **todas as 30 combinações de uma vez**, use o
   `run_all.tcl` (ver Passo 1.5 abaixo).

### Passo 1.5: rodar todas as 30 simulações em lote

Dentro do ModelSim, depois do `vlib work` inicial:

```tcl
do sim/run_all.tcl
```

Esse script percorre as 3 configs × 5 benchmarks × 2 políticas e imprime
o `hit_rate` de cada uma na ordem.

## Passo 2: abrir no Quartus (opcional — para síntese / FPGA)

1. Abra o **Quartus Prime**.
2. **File → New Project Wizard**.
3. Diretório do projeto: aponte para `sprint3/`. Nome do projeto:
   `cache_drrip`. Top-level entity: `cache`.
4. Na tela "Add Files", adicione manualmente os fontes:
   - `rtl/cache.v`
5. Família/dispositivo: escolha o FPGA que vocês têm (Cyclone III, IV,
   ou MAX 10 — pode deixar o que o instalador escolher por padrão).
6. EDA Tool Settings → Simulation → Tool name: **ModelSim‑Intel FPGA**;
   Format: **Verilog HDL**.
7. **Finish**. O Quartus abre o projeto.
8. Para apenas **compilar/sintetizar** (sem programar FPGA): menu
   `Processing → Start Compilation`. Vai gerar utilização de área,
   timing, etc., que vocês podem mostrar na apresentação.

> Nota: o testbench (`tb/*.v`) e o gerador de traces (`traces/*.c`)
> **não entram** no projeto Quartus — eles são só para simulação. O
> Quartus só sintetiza o `rtl/cache.v`.

## Estrutura do zip

```
sprint3/
├── rtl/
│   └── cache.v                  ← Único arquivo para síntese no Quartus
├── tb/
│   ├── tb_cache.v               ← Testbench (só ModelSim)
│   └── tb_top.v                 ← Wrappers de parâmetros (só ModelSim)
├── traces/
│   ├── *.hex                    ← 5 traces pré-gerados
│   └── gen_traces.c             ← Fonte do gerador (só se quiser regerar)
├── sim/
│   ├── run_modelsim.do          ← Script ModelSim (exemplo único run)
│   ├── run_all.tcl              ← Script ModelSim (todas as 30 runs)
│   ├── results.csv              ← Resultados de referência (iverilog)
│   └── *.py                     ← Geradores de gráfico (Python)
├── docs/
│   ├── hit_rate_verilog.png     ← Gráfico principal
│   └── c_vs_verilog.png         ← Validação cruzada
├── README.md                    ← README geral do projeto
└── QUARTUS.md                   ← Este arquivo
```

## Problemas comuns

- **"file not found: traces/...hex"**: o `vsim` precisa rodar **da pasta
  raiz** `sprint3/`. Confirme com `pwd` no ModelSim antes do `vsim`.
- **"can't read top-level"**: confira o nome do top-level. São 6:
  `tb_cfgA_lru/drrip`, `tb_cfgB_lru/drrip`, `tb_cfgC_lru/drrip`.
- **Resultado fica 0%**: provavelmente o trace não foi encontrado e o
  loop saiu sem nenhum acesso. Olha as linhas anteriores do Transcript.
- **Quartus reclama de `$fopen`/`$fscanf`**: normal. Essas funções são
  **não-sintetizáveis** e estão no testbench, não no `cache.v`. O
  Quartus só sintetiza `rtl/cache.v` — o resto é simulação.

## Resultados esperados (referência)

| Config | Benchmark        | LRU    | DRRIP  |
|--------|------------------|--------|--------|
| A      | streaming_hotset | 93.84% | 93.84% |
| A      | matrix_conv      | 93.65% | 93.65% |
| A      | linked_list      | 68.60% | 68.61% |
| A      | pattern_search   | 99.62% | 99.62% |
| A      | mixed_access     | 70.00% | 78.91% |
| B      | mixed_access     | 70.00% | 82.17% |
| C      | mixed_access     | 96.25% | 96.25% |

(Demais combinações em `sim/results.csv`.)
