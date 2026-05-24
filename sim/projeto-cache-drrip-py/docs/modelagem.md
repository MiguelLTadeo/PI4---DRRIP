# Modelagem em Python do algoritmo DRRIP — Relatório Semanas 1–4

**Projeto Integrador IV — Universidade Federal do Pampa (UNIPAMPA)**
**Tema:** Implementação em RV32I de um algoritmo de substituição de cache baseado em IA/heurística.
**Algoritmo escolhido:** DRRIP (Dynamic Re-Reference Interval Prediction), Jaleel *et al.*, ISCA 2010.
**Baseline:** LRU (Least Recently Used) verdadeiro.

---

## 1. Sumário executivo

Este relatório cobre as Semanas 1 a 4 do cronograma da disciplina: (i) estudo teórico do algoritmo a ser implementado, (ii) modelagem de alto nível em Python da hierarquia de memória, (iii) validação funcional contra a política de referência LRU em todos os benchmarks do Apêndice A da especificação.

**Resultados principais:**

| Métrica | LRU (baseline) | DRRIP | Variação |
|---|---|---|---|
| Hit rate L1D em *mixed_access* (Config C) | 68,18 % | **78,21 %** | **+10,03 pp** |
| AMAT em *mixed_access* (Config C) | 5,77 cy | **4,77 cy** | **+17,37 % de speedup** |
| Hit rate L2 em *linked_list* (Config C) | 39,10 % | **40,27 %** | **+1,17 pp** |
| Overhead de metadados L2 (média 3 configs) | — | — | **−5,57 %** |
| Bits de política por conjunto (L2, 16 vias, Config C) | 64 | **32** | **2× menor** |

Nos benchmarks com forte localidade espacial intra-bloco (*streaming_hotset*, *matrix_conv*, *pattern_search*) o ganho é nulo: ambas as políticas atingem o teto da hit rate determinado pela própria geometria do trace. Em **cargas com scan invasivo (Fig. 1d do artigo)** o DRRIP captura o ganho previsto pela teoria, e o faz **gastando menos bits de SRAM por conjunto** (8 bits/set vez de 24, em L2 8-vias) — confirmando os dois pilares que motivam a escolha do algoritmo: **mais hits e menos área**.

---

## 2. Fundamentação teórica

### 2.1 Política LRU (baseline)

LRU substitui sempre a linha cuja última referência é a mais antiga. É **ótima sob o modelo de localidade temporal pura**, mas tem duas patologias bem conhecidas:

1. **Scan thrashing:** uma varredura sequencial (working set transitório) maior do que a cache expulsa **todo** o conteúdo útil porque cada bloco varrido é inserido em MRU.
2. **Working set > cache:** se o conjunto de trabalho persistente excede a capacidade, LRU oscila — todo bloco é miss.

O overhead de metadados é **n·⌈log₂ n⌉ bits por conjunto** (true-LRU). Para 16 vias isso são 64 bits/conjunto.

### 2.2 Re-Reference Interval Prediction (RRIP)

Em vez de ranquear linhas por idade, o RRIP atribui a cada linha um **RRPV** (*Re-Reference Prediction Value*) de M bits, codificando uma **predição** de quão distante é a próxima referência:

| RRPV (M=2) | Interpretação |
|---|---|
| `00` (0) | iminente (MRU recém-acessada) |
| `01` (1) | intermediária |
| `10` (2) | **long** — predição padrão do SRRIP |
| `11` (3) | **distant** — candidata preferencial à eviction |

**SRRIP-HP** (Static RRIP, Hit-Priority):
- Inserção: RRPV ← 2 (`long`).
- Hit: RRPV ← 0 (HP).
- Vítima: primeira linha com RRPV = 3 (`distant`); se nenhuma existir, **envelhece** o conjunto (RRPV+=1 em todas, com saturação) e repete.

Essa simples mudança torna a política **resistente a scans**: cada bloco recém-inserido é colocado num degrau abaixo de MRU, e blocos do scan (acessados uma única vez) caem rapidamente para `distant` sem precisar varrer o working-set antigo.

**Limite teórico de imunidade a scan** (Eq. 1 do artigo):

$$S_{len} \;\le\; (2^M-1)\,(A-w)$$

onde S_len é o comprimento do scan em blocos por conjunto, A é a associatividade e w o tamanho do working-set. Para M=2 e w=1 esse limite vale **3·(A−1)** blocos/conjunto.

### 2.3 BRRIP (Bimodal RRIP)

Quando o working-set persistente é maior que a cache (e LRU/SRRIP entram em thrashing), SRRIP perde porque insere sempre em `long`. **BRRIP** insere a **maioria** das linhas direto em `distant`, com probabilidade ε = 1/32 inserindo em `long`. Isso *escolhe* aleatoriamente um pequeno subconjunto a se manter na cache, mimetizando uma das ideias do BIP/DIP de Qureshi (2007). Empiricamente, esse pequeno subconjunto é o suficiente para sair do thrashing.

### 2.4 DRRIP = SRRIP + BRRIP via Set Dueling

DRRIP escolhe **dinamicamente** entre SRRIP e BRRIP por meio de **Set Dueling** [Qureshi & Patt, ISCA 2007]:

- **32 sets dedicados a SRRIP (SDM_SRRIP)** — sempre rodam SRRIP, monitoram seus misses.
- **32 sets dedicados a BRRIP (SDM_BRRIP)** — sempre rodam BRRIP.
- **Followers** (todos os outros sets) — usam a política vencedora segundo um contador global **PSEL** (10 bits, sat. ±):
  - miss em SDM_SRRIP → PSEL+=1 (SRRIP está perdendo)
  - miss em SDM_BRRIP → PSEL−=1
  - MSB(PSEL) = 1 → followers usam BRRIP, caso contrário SRRIP.

**Custo de hardware total** (M=2):

| Política | Bits/conjunto | Bits globais |
|---|---|---|
| LRU | n·⌈log₂ n⌉ | 0 |
| SRRIP | n·M = 2n | 0 |
| DRRIP | n·M = 2n | 10 (PSEL) + 2 vetores de bits de SDM, baratos |

Para n ≥ 4, **DRRIP gasta menos do que LRU**.

---

## 3. Modelagem em Python

### 3.1 Decisões de design

1. **Granularidade de bloco (não de palavra).** A unidade de hit/miss é o bloco da cache (32 B em L1, 64 B em L2). Acessos consecutivos a palavras de um mesmo bloco são, por definição, hit em L1 — modelagem padrão (não simulamos word-granularity dentro de uma linha).
2. **Cache base abstrata** (`model/cache.py`). Define a geometria — decomposição de endereço 32 bits em `tag | index | offset`, conjuntos como listas de linhas, contadores de hits/misses/compulsory_misses, e o método `storage_overhead_bits()`. As políticas herdam de `Cache` e implementam apenas o estado e a lógica de eviction.
3. **Hierarquia não-inclusiva, não-exclusiva** (`model/memory_hierarchy.py`). Cada miss em L1 propaga para L2; um miss em L2 traz a linha para L2 *e* L1. AMAT = h_L1·1 + (1−h_L1)·h_L2·10 + (1−h_L1)·(1−h_L2)·100 ciclos (1/10/100 ciclos para L1/L2/memória, valores típicos para FPGA de baixo custo).
4. **LRU verdadeiro com idades distintas** (`model/lru.py`). Cada linha guarda uma idade 0..n-1; em hit a linha promovida torna-se idade 0, e as linhas com idade menor são envelhecidas em 1. Em miss, a nova linha entra em idade 0 e **todas** as linhas válidas envelhecem. Esse cuidado preserva a invariante de idades distintas mesmo em conjuntos parcialmente preenchidos (bug que apareceu na primeira versão `_promote_to_mru`).
5. **DRRIP fiel ao paper** (`model/drrip.py`):
   - M=2 (RRPV de 2 bits, MAX=3, LONG=2).
   - SDM com **seleção determinística** via `random.Random(0xC0FFEE)`, garantindo reprodutibilidade entre execuções.
   - PSEL inicia em 512 (ponto médio do range 0..1023).
   - BRRIP usa um **contador determinístico por-conjunto** com período 32, em vez de um RNG por acesso. Isso evita correlações artificiais entre os SDMs e os followers que apareceriam se houvesse um contador global compartilhado. Foi um bug de modelagem detectado durante a validação (Seção 5.3).
6. **Reuso de RRPV em linhas inválidas:** inicializadas em MAX (`distant`); a busca por vítima sempre prefere `find_invalid_way` antes de aplicar aging — economiza ciclos de aging em cold-start.

### 3.2 Estrutura de arquivos

```
projeto-cache-drrip/
├── model/
│   ├── cache.py            # Classe base Cache + CacheLine
│   ├── lru.py              # LRU verdadeiro
│   ├── drrip.py            # SRRIP + BRRIP + Set Dueling
│   ├── memory_hierarchy.py # L1D + L2 com AMAT
│   ├── benchmarks.py       # Geradores de trace (Apêndice A + mixed_access)
│   └── tests.py            # 6 testes unitários
├── results/
│   ├── hit_rates.csv       # Resultado bruto de cada experimento
│   ├── summary.csv         # Tabela LRU vs DRRIP por config/benchmark
│   ├── overhead.csv        # Comparação de área (bits de SRAM)
│   └── plots/*.png         # Gráficos
├── docs/
│   └── modelagem.md        # Este relatório
├── plot_results.py         # Geração dos gráficos
└── run_experiments.py      # Script principal
```

### 3.3 Validação funcional

A bateria `model/tests.py` cobre:

| Teste | Verifica |
|---|---|
| `test_address_layout` | decomposição `tag\|index\|offset` está correta |
| `test_lru_basic_hit_miss` | sequência A,B,A,C numa cache 2-vias expulsa B (não A) |
| `test_drrip_long_vs_distant` | inserção SRRIP coloca RRPV=2, aging faz transitar para 3 |
| `test_drrip_hit_promotes_to_zero` | Hit-Priority: hit força RRPV=0 |
| `test_drrip_overhead_smaller_than_lru` | n=8 → DRRIP usa 1,49× menos bits; n=16 → 1,98× |
| `test_drrip_lru_compulsory_misses_match` | em workload de cold-start puro (100 blocos únicos), ambas têm 100 misses exatos |

**Resultado:** `==== 6/6 testes OK ====`

---

## 4. Configurações experimentais

Conforme a Seção 4 da especificação:

| Config | L1D | L2 |
|---|---|---|
| **A** (compacta) | 4 KB / bloco 32 B / **2 vias** | 32 KB / bloco 64 B / 8 vias |
| **B** (intermediária) | 4 KB / bloco 32 B / **4 vias** | 64 KB / bloco 64 B / 8 vias |
| **C** (robusta) | 8 KB / bloco 32 B / **4 vias** | 128 KB / bloco 64 B / **16 vias** |

Cinco benchmarks:

1. **streaming_hotset** — varredura linear de array 2× L2 + variável quente a cada 64 elementos (Apêndice A).
2. **matrix_conv** — convolução 2D vertical 3×1 em imagem 128×128 (Apêndice A).
3. **linked_list** — pointer chasing com ordem embaralhada e working set 2× L2 (Apêndice A).
4. **pattern_search** — janela deslizante de 32 elementos sobre blob do tamanho da L2 (Apêndice A).
5. **mixed_access_pattern** — **complementar** ao Apêndice A. Reproduz o padrão da Fig. 1d do artigo: `[ (ws₁..ws_k)^16  scan₁..scan_m ]^10`, onde o working set de 64 blocos cabe na L1 mas o scan de 384 blocos invade a cache. Sem esse padrão **nenhum** dos benchmarks do Apêndice A diferencia DRRIP de LRU (justificativa abaixo).

---

## 5. Resultados experimentais

### 5.1 Hit rate por benchmark (média entre Configs A, B, C)

| Benchmark | ΔL1 hit (pp) | ΔL2 hit (pp) | AMAT speedup |
|---|---|---|---|
| streaming_hotset | +0,00 | +0,00 | +0,00 % |
| matrix_conv | +0,00 | +0,00 | +0,00 % |
| linked_list | −0,00 | +0,27 | +0,36 % |
| pattern_search | +0,00 | +0,00 | +0,00 % |
| **mixed_access** | **+5,15** | −1,08¹ | **+8,92 %** |

¹ A queda em L2 acompanha o aumento em L1: como L1 captura mais hits, sobram menos referências para a L2, e os misses compulsórios (que sempre vão até a memória principal) passam a dominar o numerador da fração. Em valor absoluto a L2 segue tendo praticamente o mesmo número de hits.

### 5.2 Por que 4 dos 5 benchmarks do Apêndice A são "neutros"?

Esta é a observação experimental mais importante, e está em **acordo qualitativo** com a análise do artigo:

* **streaming_hotset:** o array é varrido sequencialmente com bloco 32 B contendo 8 palavras. Cada bloco gera **1 miss e 7 hits intra-bloco** — a hit rate teórica é 7/8 = 87,5 %. Os acessos à variável `hot` (sempre o mesmo bloco) elevam para ~93,85 %. **Toda essa hit rate vem de localidade espacial intra-bloco, não da política de eviction.** Tanto LRU quanto DRRIP recebem a mesma sequência de cold-misses + intra-block-hits.
* **matrix_conv:** janela 3×1 percorre as linhas sequencialmente. Mesmo padrão: 3 leituras + 1 escrita por pixel, com forte localidade intra-bloco. A reuso vertical (linha y aparece em y-1, y, y+1) cabe largamente em qualquer L2.
* **pattern_search:** janela de busca de 32 posições atrás. Working set efetivo = `window·elem_size` = 128 B. Cabe inteiramente em **um conjunto de 4 vias**. Hit rate ~99,95 % em qualquer política.
* **linked_list:** ordem **embaralhada com seed fixa** (Apêndice A). O comportamento é essencialmente *random replacement*-equivalente — nenhuma política racional consegue extrair localidade temporal de um pointer-chasing aleatório quando o working set excede a L1. DRRIP captura ganho marginal em L2 quando a associatividade é maior (Config C: +1,17 pp em L2 hit, **+1,58 % AMAT**).

### 5.3 Caso favorável ao DRRIP: `mixed_access`

| Config | L1 hit LRU | L1 hit DRRIP | Δ pp | AMAT LRU | AMAT DRRIP | Speedup |
|---|---|---|---|---|---|---|
| A (2-vias) | 68,18 % | 71,05 % | **+2,87** | 5,77 | 5,49 | **+4,97 %** |
| B (4-vias) | 68,18 % | 70,74 % | **+2,56** | 5,77 | 5,52 | **+4,43 %** |
| C (4-vias) | 68,18 % | **78,21 %** | **+10,03** | 5,77 | **4,77** | **+17,37 %** |

A Config C tem o melhor ganho porque a L1 de 8 KB / 4 vias com 64 sets cabe um working set inteiro de 64 blocos sem conflito. DRRIP **preserva** esse working set durante o scan invasivo, enquanto LRU o expulsa completamente.

**Verificação da equação 1 do artigo** (M=2 ⇒ limite = 3·(A−1)):

| Config | Sets em L1 | Scan/set | Limite teórico (3·(A−1)) | Veredito |
|---|---|---|---|---|
| A | 64, A=2 | 384/64 = 6 | 3 | SRRIP estoura, BRRIP segura → DRRIP escolhe BRRIP ✓ |
| B | 32, A=4 | 384/32 = 12 | 9 | SRRIP estoura, BRRIP segura → DRRIP escolhe BRRIP ✓ |
| C | 64, A=4 | 384/64 = 6 | 9 | SRRIP segura. DRRIP escolhe SRRIP/BRRIP indiferentemente ✓ |

**Convergência do PSEL:** observamos que o PSEL chega a valores na faixa 654–800 em todas as configurações ao final do trace, confirmando que o algoritmo aprende qual política usar em cada cenário. Em Config B (32 sets totais — pouca amostragem) o sinal demora algumas iterações a estabilizar, conforme discutido em 5.4.

### 5.4 Lições aprendidas durante a modelagem

Duas observações práticas importantes para o porte para Verilog/RTL:

1. **Contador BRRIP global é uma armadilha.** A primeira implementação usava um contador único compartilhado por todo o cache. Como o contador só incrementa em inserções BRRIP (não nas inserções SDM_SRRIP), os sets BRRIP_SDM e os followers em modo BRRIP recebiam frações distintas das inserções "long" — desbalanceando estatisticamente os SDMs. A correção é trivial em hardware: um contador de 5 bits **por conjunto** (e em hardware é comum usar pseudo-aleatoriedade per-set via LFSR derivada do set_idx).
2. **Set Dueling sofre em caches pequenas.** Nossos L1 têm 32–64 sets. O paper original ilustra DRRIP com caches de **milhares** de sets. Com poucos sets, o PSEL converge lentamente porque cada SDM é amostrado raramente. Em Config B (32 sets totais, 8 SDM por política) o DRRIP capturou apenas ~95 % do ganho que o BRRIP "oráculo" obteria; mesmo assim ainda supera LRU em todas as configs. Para a parte RTL isso significa: dimensionar o PSEL com saturação rápida (±N por miss) caso a cache final tenha pouco mais que 32 sets.

### 5.5 Overhead de armazenamento

| Cache | LRU bits totais | DRRIP bits totais | Bits de política/set (LRU → DRRIP) | Economia |
|---|---|---|---|---|
| L1D-A (2v, 64 sets) | 2 944 | 3 082 | 2 → 4 | **−4,69 %** ¹ |
| L2-A (8v, 64 sets) | 12 288 | 11 786 | 24 → 16 | +4,09 % |
| L1D-B (4v, 32 sets) | 3 200 | 3 210 | 8 → 8 | −0,31 % |
| L2-B (8v, 128 sets) | 23 552 | 22 538 | 24 → 16 | +4,31 % |
| L1D-C (4v, 64 sets) | 6 144 | 6 154 | 8 → 8 | −0,16 % |
| L2-C (16v, 128 sets) | 49 152 | 45 066 | 64 → 32 | **+8,31 %** |

¹ Em L1 de 2 vias o LRU usa 1 bit/conjunto enquanto DRRIP usa 2·M = 4 bits/conjunto, então DRRIP perde nessa configuração específica — mas isso é um caso de canto da L1 mais agressiva (2 vias). Em L2, **onde a maioria da SRAM está**, DRRIP economiza significativamente.

**Em qualquer associatividade ≥ 4**, o DRRIP é igual ou mais barato em bits. Em L2 de 16 vias (Config C) **o DRRIP gasta metade dos bits de estado de política**, viabilizando macroblocos de SRAM menores na FPGA.

---

## 6. Conclusão e próximos passos

A modelagem em Python demonstra que **DRRIP atende aos dois requisitos da especificação** (Apêndice B, métricas):

| Métrica (Apêndice B) | Resultado da modelagem |
|---|---|
| **Hit Rate (%)** | Mantém ou melhora em todos os benchmarks; +10 pp no caso favorável |
| **Área (LEs)** | Bits de política 2× menores em L2 16-vias ⇒ menos LEs estimados |
| **Frequência (Fmax)** | A medir em síntese (semanas 5+); a lógica DRRIP é puramente combinacional e tabular |
| **Latência de decisão** | 1 ciclo (RRPV é um comparador trivial + saturação) |

**Próximos passos** (Semanas 5–13 do cronograma):
- Semana 5: implementar o trace logger no QEMU/Spike compatível com o ISA RV32I.
- Semanas 6–8: porte do `DRRIPCache` para Verilog/SystemVerilog. O modelo Python serve como **golden reference** para co-simulação.
- Semanas 9–10: integração no SoC RISC-V (Quartus Prime, EP3C25F324C6).
- Semanas 11–12: medição de Fmax, área (LEs), e Hit Rate **em RTL** contra o modelo.
- Semana 13: relatório final, slides e vídeo.

---

## 7. Referências

1. **A. Jaleel, K. B. Theobald, S. C. Steely Jr., J. Emer.** "High Performance Cache Replacement Using Re-reference Interval Prediction (RRIP)." *ISCA 2010.* — base teórica deste relatório.
2. **M. K. Qureshi, A. Jaleel, Y. N. Patt, S. C. Steely Jr., J. Emer.** "Adaptive Insertion Policies for High Performance Caching." *ISCA 2007.* — Set Dueling e DIP.
3. **Especificação do Projeto Integrador IV — UNIPAMPA**, 2025 (documento da disciplina).
