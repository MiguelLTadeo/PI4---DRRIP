# LRU — Diagrama RTL Estrutural

Mapeamento do simulador C (`lru.c` / `cache.c`) para componentes físicos de hardware
implementáveis em Verilog / FPGA.

---

## 1. Mapeamento C → Hardware

| Elemento C | Componente RTL | Tipo de hardware |
|---|---|---|
| `cache_line_t.valid` | `valid_regfile[N_SETS][N_WAYS]` | Flip-flop (1 bit / linha) |
| `cache_line_t.tag` | `tag_sram[N_SETS][N_WAYS][TAG_W]` | SRAM dual-port (BRAM/LUTRAM) |
| `cache_line_t.lru_age` | `age_regfile[N_SETS][N_WAYS][AGE_W]` | Flip-flop (AGE_W bits / linha) |
| `cache_set_of(addr)` | Barramento `addr[OFF+IDX-1:OFF]` | Fio — sem lógica |
| `cache_tag_of(addr)` | Barramento `addr[31:OFF+IDX]` | Fio — sem lógica |
| `cache_find_way()` | `TAG_COMPARATOR` | N_WAYS comparadores em paralelo + codificador de prioridade |
| `cache_find_invalid_way()` | `INVALID_FINDER` | Codificador de prioridade em `~valid_rd` |
| `find_lru_victim()` | `LRU_VICTIM_SEL` | Árvore de torneio (max finder) |
| `on_hit()` | `AGE_UPDATE` (caminho HIT) | Lógica combinacional por way |
| `insert_as_mru()` | `AGE_UPDATE` (caminho MISS) + `WRITE_CTRL` | Lógica combinacional + FF |
| `lru_access()` | `CTRL_FSM` | Moore FSM sequencial |

---

## 2. Parâmetros e Larguras de Barramento

| Parâmetro | Fórmula | Config A (4KB/32B/2v) | Config B (4KB/32B/4v) | Config C (8KB/32B/4v) |
|---|---|---|---|---|
| `ADDR_W` | 32 | 32 | 32 | 32 |
| `OFF_W` | log₂(BLOCK_B) | 5 | 5 | 5 |
| `N_SETS` | SIZE/(BLOCK×WAYS) | 64 | 32 | 64 |
| `IDX_W` | log₂(N_SETS) | 6 | 5 | 6 |
| `TAG_W` | ADDR_W−OFF_W−IDX_W | 21 | 22 | 21 |
| `N_WAYS` | associatividade | 2 | 4 | 4 |
| `WAY_W` | log₂(N_WAYS) | 1 | 2 | 2 |
| `AGE_W` | log₂(N_WAYS) | 1 | 2 | 2 |
| SRAM total | N_SETS×N_WAYS×TAG_W | 2 688 b | 2 816 b | 5 376 b |
| Age total | N_SETS×N_WAYS×AGE_W | 128 b | 256 b | 512 b |

---

## 3. Diagrama RTL Completo

**Legenda de cores:**
- 🔵 Azul claro — lógica combinacional pura
- 🟢 Verde — SRAM / banco de registradores (armazenamento)
- 🟡 Amarelo — multiplexador / seletor
- 🟠 Laranja — lógica sequencial / registrador de saída
- 🔴 Rosa — portas de I/O do módulo top

```mermaid
flowchart TD
    classDef comb  fill:#dae8fc,stroke:#6c8ebf,color:#000,font-size:13px
    classDef mem   fill:#d5e8d4,stroke:#82b366,color:#000,font-size:13px
    classDef mux   fill:#fff2cc,stroke:#d6b656,color:#000,font-size:13px
    classDef seq   fill:#ffe6cc,stroke:#d79b00,color:#000,font-size:13px
    classDef io    fill:#f8cecc,stroke:#b85450,color:#000,font-size:13px

    %% ════════════════════════════════════════════
    %% PORTAS DE I/O
    %% ════════════════════════════════════════════
    IN_ADDR(["addr [ADDR_W-1:0]"]):::io
    IN_REQ(["valid_req"]):::io
    IN_CLK(["clk / rst_n"]):::io
    OUT_HIT(["hit_out"]):::io
    OUT_STALL(["stall"]):::io

    %% ════════════════════════════════════════════
    %% BLOCO 1 — DECODIFICADOR DE ENDEREÇO
    %% addr_decoder — combinacional (somente fios)
    %% ════════════════════════════════════════════
    subgraph B1["① ADDR_DECODER — combinacional (somente fios)"]
        ADEC["set_idx = addr [ OFF_W + IDX_W - 1  :  OFF_W ]<br/>tag_in  = addr [ ADDR_W - 1  :  OFF_W + IDX_W ]"]:::comb
    end

    %% ════════════════════════════════════════════
    %% BLOCO 2 — ARRAYS DE ARMAZENAMENTO
    %% ════════════════════════════════════════════
    subgraph B2["② ARRAYS DE ARMAZENAMENTO — leitura assíncrona (LUTRAM) ou 1 ciclo (BRAM)"]
        TAGSRAM[("TAG_SRAM<br/>─────────────────<br/>N_SETS × N_WAYS × TAG_W<br/>SRAM dual-port<br/>rd: set_idx → tag_rd[]<br/>wr: we_tag, set, way, data")]:::mem
        VALREG[("VALID_REG<br/>─────────────────<br/>N_SETS × N_WAYS × 1 bit<br/>Banco de flip-flops<br/>reset: todos 0")]:::mem
        AGEREG[("AGE_REG<br/>─────────────────<br/>N_SETS × N_WAYS × AGE_W<br/>Banco de flip-flops<br/>reset: age[w] = w")]:::mem
    end

    %% ════════════════════════════════════════════
    %% BLOCO 3 — COMPARADOR DE TAGS (hit detection)
    %% Mapeia cache_find_way()
    %% ════════════════════════════════════════════
    subgraph B3["③ TAG_COMPARATOR — N_WAYS comparadores em paralelo"]
        TC["Para cada way w ∈ [0 .. N_WAYS-1]:<br/>  hit_vec[w] = valid_rd[w] AND (tag_rd[w] == tag_in)<br/>─────────────────────────────────────────────<br/>  hit_any = OR_REDUCE(hit_vec)<br/>  hit_way = PriorityEncode(hit_vec)  →  WAY_W bits"]:::comb
    end

    %% ════════════════════════════════════════════
    %% BLOCO 4 — SELEÇÃO DE VÍTIMA
    %% Mapeia cache_find_invalid_way() + find_lru_victim()
    %% ════════════════════════════════════════════
    subgraph B4["④ SELEÇÃO DE VÍTIMA"]
        INVF["INVALID_FINDER<br/>─────────────────<br/>inv_vec[w] = NOT valid_rd[w]<br/>has_inv = OR_REDUCE(inv_vec)<br/>inv_way = PriorityEncode(inv_vec)"]:::comb
        LRUV["LRU_VICTIM_SEL<br/>─────────────────────────────<br/>Árvore de torneio log₂(N_WAYS) estágios<br/>Compara age_rd[w] par a par<br/>victim_lru = argmax_w(age_rd[w])"]:::comb
        VMUX{{"VICTIM_MUX<br/>─────────────<br/>has_inv == 1<br/>→ inv_way<br/>has_inv == 0<br/>→ victim_lru"}}:::mux
    end

    %% ════════════════════════════════════════════
    %% BLOCO 5 — LÓGICA DE ATUALIZAÇÃO DE IDADES
    %% Mapeia on_hit() e insert_as_mru()
    %% Lógica paralela para todos os N_WAYS ways
    %% ════════════════════════════════════════════
    subgraph B5["⑤ AGE_UPDATE — lógica combinacional, todos os ways em paralelo"]
        AU_HIT["HIT PATH  — on_hit():<br/>prev_age = age_rd[hit_way]<br/>age_next[hit_way] = 0<br/>age_next[w] = age_rd[w] + 1<br/>  se  valid_rd[w] AND age_rd[w] &lt; prev_age<br/>  senão  age_rd[w]  (inalterado)"]:::comb
        AU_MIS["MISS PATH  — insert_as_mru():<br/>age_next[victim] = 0<br/>age_next[w] = age_rd[w] + 1<br/>  se  valid_rd[w] AND age_rd[w] &lt; (N_WAYS-1)<br/>  senão  age_rd[w]  (inalterado)"]:::comb
        AMUX{{"HIT_SEL_MUX<br/>hit_any == 1<br/>→ AU_HIT<br/>hit_any == 0<br/>→ AU_MIS"}}:::mux
    end

    %% ════════════════════════════════════════════
    %% BLOCO 6 — WRITE-BACK CONTROLLER
    %% Registra escritas na borda de subida do clock
    %% ════════════════════════════════════════════
    subgraph B6["⑥ WRITE_CTRL — registra na borda ↑clk quando write_en=1"]
        WB["EM HIT:<br/>  AGE_REG[set_idx][*]  ←  age_next[*]<br/>EM MISS:<br/>  TAG_SRAM[set_idx][victim]   ←  tag_in<br/>  VALID_REG[set_idx][victim]  ←  1<br/>  AGE_REG[set_idx][*]         ←  age_next[*]"]:::seq
    end

    %% ════════════════════════════════════════════
    %% BLOCO 7 — FSM DE CONTROLE
    %% Mapeia lru_access() — fluxo de controle
    %% ════════════════════════════════════════════
    subgraph B7["⑦ CTRL_FSM — Moore FSM de 2 estados (pipeline 1 ciclo de latência)"]
        FSM["IDLE ──(valid_req=1)──▶ TAG_CMP ──(1 ciclo)──▶ UPDATE ──▶ IDLE<br/>──────────────────────────────────────────────────────<br/>IDLE   : rd_en=0, we=0, stall=0<br/>TAG_CMP: rd_en=1, we=0, stall=1  ← lê arrays<br/>UPDATE : rd_en=0, we=1, stall=0  ← write_ctrl escreve"]:::seq
    end

    %% ════════════════════════════════════════════
    %% CONEXÕES DE DADOS
    %% ════════════════════════════════════════════
    IN_ADDR --> ADEC
    IN_REQ  --> FSM
    IN_CLK  --> FSM
    IN_CLK  --> WB

    ADEC -- "set_idx [IDX_W]" --> TAGSRAM
    ADEC -- "set_idx [IDX_W]" --> VALREG
    ADEC -- "set_idx [IDX_W]" --> AGEREG
    ADEC -- "tag_in [TAG_W]"  --> TC
    ADEC -- "tag_in [TAG_W]"  --> WB

    TAGSRAM -- "tag_rd [N_WAYS × TAG_W]" --> TC
    VALREG  -- "valid_rd [N_WAYS]"        --> TC
    VALREG  -- "valid_rd [N_WAYS]"        --> INVF
    VALREG  -- "valid_rd [N_WAYS]"        --> AU_HIT
    VALREG  -- "valid_rd [N_WAYS]"        --> AU_MIS
    AGEREG  -- "age_rd [N_WAYS × AGE_W]" --> LRUV
    AGEREG  -- "age_rd [N_WAYS × AGE_W]" --> AU_HIT
    AGEREG  -- "age_rd [N_WAYS × AGE_W]" --> AU_MIS

    TC -- "hit_any"         --> OUT_HIT
    TC -- "hit_any"         --> AMUX
    TC -- "hit_any"         --> FSM
    TC -- "hit_way [WAY_W]" --> AU_HIT
    TC -- "hit_way [WAY_W]" --> AU_MIS

    INVF -- "has_inv"         --> VMUX
    INVF -- "inv_way [WAY_W]" --> VMUX
    LRUV -- "victim_lru [WAY_W]" --> VMUX
    VMUX -- "victim [WAY_W]"     --> AU_MIS
    VMUX -- "victim [WAY_W]"     --> WB

    AU_HIT -- "age_next_hit [N_WAYS×AGE_W]" --> AMUX
    AU_MIS -- "age_next_mis [N_WAYS×AGE_W]" --> AMUX
    AMUX   -- "age_next [N_WAYS×AGE_W]"     --> WB

    FSM -- "rd_en"              --> TAGSRAM & VALREG & AGEREG
    FSM -- "we_tag"             --> WB
    FSM -- "we_valid"           --> WB
    FSM -- "we_age"             --> WB
    FSM -- "stall"              --> OUT_STALL

    WB -- "wr_tag_data/addr/en"   --> TAGSRAM
    WB -- "wr_valid_data/addr/en" --> VALREG
    WB -- "wr_age_data/addr/en"   --> AGEREG
```

---

## 4. FSM de Controle

```mermaid
stateDiagram-v2
    [*] --> IDLE

    IDLE   : IDLE\nrd_en=0 · we=0 · stall=0
    TAGCMP : TAG_CMP\nrd_en=1 · we=0 · stall=1
    UPDATE : UPDATE\nrd_en=0 · we=1 · stall=0

    IDLE   --> TAGCMP : valid_req=1
    IDLE   --> IDLE   : valid_req=0
    TAGCMP --> UPDATE : (sempre após 1 ciclo)
    UPDATE --> IDLE   : (sempre após 1 ciclo)
```

---

## 5. Descrição dos Blocos

### ① ADDR_DECODER
Apenas fios. Extrai `set_idx` e `tag_in` de `addr` via seleção de bits — zero LUTs.

```
set_idx = addr[OFF_W + IDX_W - 1 : OFF_W]
tag_in  = addr[ADDR_W - 1 : OFF_W + IDX_W]
```

### ② ARRAYS DE ARMAZENAMENTO
Três estruturas independentes acessadas pelo mesmo `set_idx`:
- **TAG_SRAM**: leitura de `N_WAYS` tags completos na borda de clock (BRAM) ou assíncrona (LUTRAM).
- **VALID_REG**: flip-flops, reset assíncrono para 0.
- **AGE_REG**: flip-flops, reset inicializa `age[w] = w` para idades distintas (invariante do LRU).

### ③ TAG_COMPARATOR
`N_WAYS` comparadores de `TAG_W` bits em paralelo. Cada comparador gera `hit_vec[w]`. A saída `hit_way` é um codificador de prioridade — qualquer way pode ser hit, mas ao mais uma por conjunto por invariante do LRU.

### ④ SELEÇÃO DE VÍTIMA
- **INVALID_FINDER**: codificador de prioridade em `~valid`. Se existe linha inválida, ela é a vítima direta (capacidade livre, sem desalojo).
- **LRU_VICTIM_SEL**: árvore de torneio de profundidade `log₂(N_WAYS)`. Cada nó compara dois `age` values e passa o maior. Raiz retorna `victim_lru`.
- **VICTIM_MUX**: seleciona `inv_way` se `has_inv=1`, senão `victim_lru`.

### ⑤ AGE_UPDATE
Lógica paralela em todos os `N_WAYS` ways. Implementa as duas funções C:
- **HIT (`on_hit`)**: `age[hit_way]←0`; ways com `age < prev_age` são incrementados em 1.
- **MISS (`insert_as_mru`)**: `age[victim]←0`; ways válidos com `age < N_WAYS-1` são incrementados em 1.

Em hardware, cada way tem um multiplexador de 2 bits de seleção:
```
age_next[w] = (w == anchor) ? AGE_W'(0)
            : (cond[w])     ? age_rd[w] + 1
            :                 age_rd[w];
```

### ⑥ WRITE_CTRL
Registra os resultados computados por `AGE_UPDATE` (e `tag_in`/`victim` no caso de miss) nos arrays de armazenamento na borda ↑clk, controlado pelos sinais `we_*` da FSM.

### ⑦ CTRL_FSM
Moore FSM de 2 estados operacionais. Em implementação pipelinada, pode aceitar nova requisição a cada ciclo depois do estado de leitura (throughput = 1 acesso/ciclo, latência = 2 ciclos).
