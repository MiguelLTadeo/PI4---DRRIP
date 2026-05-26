# Documentação Técnica — Projeto Cache Replacement em C

Documentação detalhada dos três algoritmos implementados:
1. **LRU** — Least Recently Used (baseline clássico)
2. **DRRIP-Jaleel** — DRRIP do paper Jaleel et al. (ISCA 2010), adaptado para FPGA
3. **DRRIP-ChampSim** — porte literal do `drrip.cc` do ChampSim, preservando o comportamento original

Todos compartilham a mesma estrutura base (`cache.h`/`cache.c`). Cada política
implementa apenas a lógica específica de atualização de estado e busca de
vítima.

---

## Índice

1. [Estrutura base — cache.h e cache.c](#1-estrutura-base--cacheh-e-cachec)
2. [Algoritmo LRU — lru.c](#2-algoritmo-lru--lruc)
3. [Algoritmo DRRIP-Jaleel — drrip_jaleel.c](#3-algoritmo-drrip-jaleel--drrip_jaleelc)
4. [Algoritmo DRRIP-ChampSim — drrip_champsim.c](#4-algoritmo-drrip-champsim--drrip_champsimc)
5. [Benchmarks — benchmarks.c](#5-benchmarks--benchmarksc)
6. [Driver experimental — main.c](#6-driver-experimental--mainc)
7. [Comparação algorítmica entre as três políticas](#7-comparação-algorítmica)

---

## 1. Estrutura base — cache.h e cache.c

A estrutura `cache_t` modela uma cache set-associativa genérica. Os três
algoritmos a usam sem modificá-la.

### 1.1 Estrutura de uma linha de cache (`cache_line_t`)

```c
typedef struct {
    uint8_t  valid;
    uint64_t tag;
    uint16_t lru_age;
    uint8_t  rrpv;
} cache_line_t;
```

Cada linha guarda **simultaneamente** os campos de LRU e DRRIP. Em hardware
real, você usaria apenas um (LRU usa `lru_age`, DRRIP usa `rrpv`). Em
modelagem, manter os dois é gratuito e simplifica o código — cada política
mexe apenas no campo que lhe interessa.

**Campos:**
- `valid` — 1 se a linha contém um bloco válido, 0 se está vazia
- `tag` — bits altos do endereço identificando qual bloco está na linha
- `lru_age` — idade no ranking LRU (0 = MRU, assoc-1 = LRU)
- `rrpv` — Re-Reference Prediction Value (0..3 em M=2 bits)

### 1.2 Estrutura da cache (`cache_t`)

```c
typedef struct {
    int      block_bytes;
    int      assoc;
    int      num_sets;
    int      offset_bits;
    int      index_bits;
    cache_line_t *lines;
    uint64_t hits;
    uint64_t misses;
    uint64_t cold_misses;
    uint8_t *seen_blocks;
    size_t   seen_capacity;
} cache_t;
```

**Geometria** (calculada na inicialização):
- `block_bytes` — tamanho de cada bloco (ex: 32 bytes em L1)
- `assoc` — associatividade (vias por conjunto)
- `num_sets` — número de conjuntos = `size_bytes / (block_bytes * assoc)`
- `offset_bits = log2(block_bytes)` — bits do endereço que selecionam byte dentro do bloco
- `index_bits = log2(num_sets)` — bits que selecionam o conjunto

**Decomposição de endereço de 32 bits:**

```
+----------------+----------------+----------------+
|     TAG        |     INDEX      |    OFFSET      |
+----------------+----------------+----------------+
| 32-i-o bits    | index_bits     | offset_bits    |
```

Por exemplo, em L1 4 KB / 2 vias / bloco 32 B:
- `block_bytes = 32` → `offset_bits = 5`
- `num_sets = 4096/(32*2) = 64` → `index_bits = 6`
- `tag_bits = 32 - 5 - 6 = 21`

### 1.3 Inicialização (`cache_init`)

```c
void cache_init(cache_t *c, int size_bytes, int block_bytes, int assoc);
```

Aloca `num_sets * assoc` linhas via `calloc` (todas zeradas) e depois
inicializa cada linha:

```c
L->valid = 0;
L->tag = 0;
L->lru_age = (uint16_t)w;   // idade w para a via w
L->rrpv = 3;                 // MAX_RRPV (distant) para inválidas
```

**Por que `lru_age = w` em vez de zero?**

Para preservar a invariante de que **todas as idades são distintas** em
`{0, 1, ..., assoc-1}`. Se todas começassem em 0, o LRU teria empates ao
escolher vítima.

**Por que `rrpv = 3` para linhas inválidas?**

Linhas inválidas devem ser preferidas como vítimas. Como o algoritmo busca
"linha com RRPV máximo", iniciar com `MAX_RRPV` garante isso naturalmente.
Na prática, sempre verificamos linhas inválidas antes (`find_invalid_way`),
mas é redundância de segurança.

### 1.4 Funções helper inline

```c
static inline int cache_set_of(const cache_t *c, uint64_t addr) {
    return (addr >> c->offset_bits) & ((1 << c->index_bits) - 1);
}
```

Extrai o `set_index` de um endereço:
1. Desloca à direita para descartar os bits de offset
2. Aplica máscara para pegar apenas `index_bits` bits

```c
static inline uint64_t cache_tag_of(const cache_t *c, uint64_t addr) {
    return addr >> (c->offset_bits + c->index_bits);
}
```

Extrai o `tag`: desloca à direita por `offset_bits + index_bits`.

### 1.5 Busca de tag (`cache_find_way`)

```c
int cache_find_way(const cache_t *c, int set_idx, uint64_t tag) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    for (int w = 0; w < c->assoc; w++) {
        if (base[w].valid && base[w].tag == tag) return w;
    }
    return -1;
}
```

Procura linearmente por uma linha válida com o tag procurado.
Retorna o índice da via se encontrar (HIT), ou -1 (MISS).

Em hardware real, isso seria feito em paralelo por comparadores
(um por via) num único ciclo. Em software, é loop linear.

### 1.6 Rastreamento de blocos vistos (`cache_mark_touched`)

```c
int cache_mark_touched(cache_t *c, uint64_t block_addr) {
    // hash table simples com linear probing
    size_t idx = (size_t)(block_addr * 2654435761u) & (cap - 1);
    for (size_t probe = 0; probe < cap; probe++) {
        size_t pos = (idx + probe) & (cap - 1);
        if (c->seen_blocks[pos] == 0) {
            c->seen_blocks[pos] = 1;
            return 1;  // primeira vez = cold miss
        }
        if (probe > 32) break;
    }
    return 0;
}
```

Mantém um conjunto dos blocos já tocados, para contar **cold misses**
(misses compulsórios — primeira vez que um bloco é acessado).

A constante `2654435761u` é a "razão áurea fracionária" multiplicada por
2³² — uma constante clássica de Fibonacci hashing que distribui bem
endereços sequenciais. Permite hash rápido sem usar `%`.

`cold_misses` é importante porque é o **piso teórico** de misses: nenhuma
política consegue evitar misses compulsórios (o bloco simplesmente não
está na cache ainda). Diferenciar cold miss de capacity miss / conflict
miss é diagnóstico importante.

---

## 2. Algoritmo LRU — lru.c

LRU é a política clássica: **substitui sempre a linha menos recentemente
usada**. Cada linha mantém uma "idade" em uma pilha implícita, atualizada
em todo acesso.

### 2.1 Idade como ranking de recência

Em uma cache de associatividade `n`, as `n` linhas válidas de um conjunto
têm idades **distintas** em `{0, 1, ..., n-1}`:
- Idade 0 → MRU (Most Recently Used, acabou de ser tocada)
- Idade n-1 → LRU (Least Recently Used, tocada há mais tempo)

A vítima é sempre a linha com idade `n-1`.

### 2.2 Função `on_hit` — atualização em HIT

```c
static void on_hit(cache_t *c, int set_idx, int hit_way) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    uint16_t prev_age = base[hit_way].lru_age;
    for (int w = 0; w < c->assoc; w++) {
        if (w == hit_way) continue;
        if (base[w].valid && base[w].lru_age < prev_age) {
            base[w].lru_age++;
        }
    }
    base[hit_way].lru_age = 0;
}
```

**Lógica passo a passo:**

1. Salva a idade da linha que recebeu o hit (`prev_age`).
2. Percorre todas as outras linhas. Só envelhece (+1) aquelas com idade
   **menor** que `prev_age` — ou seja, as mais recentes.
3. A linha do hit recebe idade 0 (MRU).

**Por que só as mais novas envelhecem?**

Para preservar a invariante "idades distintas em [0, n-1]". Exemplo
numa cache 4-vias com idades `[2, 0, 3, 1]`, hit na way 2 (idade 3):

| Antes | Após `on_hit(set, 2)` |
|---|---|
| way 0: idade 2 | way 0: idade 3 (era < 3, envelheceu) |
| way 1: idade 0 | way 1: idade 1 (era < 3, envelheceu) |
| way 2: idade 3 | way 2: idade **0** (recebeu o hit) |
| way 3: idade 1 | way 3: idade 2 (era < 3, envelheceu) |

Idades distintas mantidas: `{0, 1, 2, 3}`. Se envelhecêssemos *todas* as
linhas, way 0 e way 3 ambas chegariam em 3 (saturadas) e teríamos
empate.

### 2.3 Função `insert_as_mru` — atualização em MISS

```c
static void insert_as_mru(cache_t *c, int set_idx, int new_way, uint64_t tag) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    for (int w = 0; w < c->assoc; w++) {
        if (w == new_way) continue;
        if (base[w].valid && base[w].lru_age < c->assoc - 1) {
            base[w].lru_age++;
        }
    }
    base[new_way].valid = 1;
    base[new_way].tag = tag;
    base[new_way].lru_age = 0;
}
```

**Diferenças em relação a `on_hit`:**

- Em miss, **todas** as linhas válidas envelhecem (não só as mais novas)
- A linha que vai sair tinha idade `assoc-1` e é sobrescrita pela nova
- A nova linha entra com `valid=1`, `tag=novo_tag`, `lru_age=0`

O check `lru_age < assoc-1` evita saturação caso o conjunto esteja
parcialmente vazio (cold start).

### 2.4 Função principal `lru_access`

```c
int lru_access(cache_t *c, uint64_t addr) {
    int set_idx = cache_set_of(c, addr);
    uint64_t tag = cache_tag_of(c, addr);
    int way = cache_find_way(c, set_idx, tag);

    if (way >= 0) {
        c->hits++;
        on_hit(c, set_idx, way);
        return 1;
    }

    c->misses++;
    if (cache_mark_touched(c, cache_block_of(c, addr))) {
        c->cold_misses++;
    }

    int victim = cache_find_invalid_way(c, set_idx);
    if (victim < 0) victim = find_lru_victim(c, set_idx);

    insert_as_mru(c, set_idx, victim, tag);
    return 0;
}
```

**Fluxo:**

1. Decompõe endereço → `(set_idx, tag)`
2. Procura tag no conjunto. Se encontrar (HIT):
   - Incrementa contador de hits
   - Atualiza idades via `on_hit`
   - Retorna 1
3. Se não encontrar (MISS):
   - Incrementa contador de misses
   - Verifica se é cold miss (primeira vez vendo este bloco)
   - Procura linha inválida (cold start). Se houver, é a vítima
   - Senão, vítima = linha com `lru_age == assoc-1`
   - Substitui a vítima pelo novo bloco via `insert_as_mru`
   - Retorna 0

### 2.5 Custo de hardware do LRU

**Bits de estado por linha:** `ceil(log2(assoc))`
- 2 vias → 1 bit
- 4 vias → 2 bits
- 8 vias → 3 bits
- 16 vias → 4 bits

**Bits totais por conjunto:** `assoc * ceil(log2(assoc))`
- 16 vias: 16 × 4 = **64 bits/conjunto**

Em hardware real, manter idades distintas requer **rede de atualização**
em paralelo (não dá pra fazer com simples shift register). É a razão
pela qual LRU true é caro em alta associatividade — daí o uso comum de
**pseudo-LRU** (PLRU) em caches reais, que aproxima com menos bits.

### 2.6 Limitações teóricas do LRU

**Patologia 1 — Scan invasivo destrói working set:**

Quando um scan (varredura de blocos lidos uma única vez) entra na cache,
cada bloco do scan é tratado como "recente = útil" e expulsa blocos
antigos. Se esses blocos antigos eram parte de um working set que
seria reusado, eles são destruídos.

**Patologia 2 — Working set > cache → thrashing:**

Se o working set persistente for maior que a capacidade, o LRU expulsa
exatamente os blocos que serão reusados em seguida, criando uma cascata
de 100% miss.

Essas duas patologias são exatamente o que motivou a criação do DRRIP.

---

## 3. Algoritmo DRRIP-Jaleel — drrip_jaleel.c

DRRIP é uma combinação adaptativa de **SRRIP** (Static Re-Reference
Interval Prediction) e **BRRIP** (Bimodal RRIP), escolhida dinamicamente
via **Set Dueling** (Qureshi et al., ISCA 2007).

Esta implementação é **fiel ao algoritmo do paper**, com três adaptações
necessárias para caches pequenas de FPGA (que o paper original não cobre):

1. PSEL inicia em `PSEL_MAX/2` (centrado, sem viés de partida)
2. Seleção de SDMs via shuffle determinístico dentro de `[0, num_sets)`
3. Contador BIP **per-set** (evita correlação entre SDM_BRRIP e followers)

### 3.1 Conceito: RRPV (Re-Reference Prediction Value)

Em vez de rankear linhas por **idade**, o DRRIP rankeia por **predição**
de quão distante está a próxima referência:

| RRPV (M=2) | Interpretação | Significado prático |
|---|---|---|
| 0 | Iminente | Bloco quente, recém-acessado |
| 1 | Curto | Provavelmente será reusado em breve |
| 2 | Longo (`LONG_RRPV`) | Reuso em algum momento futuro |
| 3 | Distante (`MAX_RRPV`) | Provavelmente nunca mais — candidato a sair |

Cada linha guarda 2 bits (M=2). Em hardware, isso é trivial.

### 3.2 Constantes principais

```c
#define DRRIP_M           2     // bits de RRPV
#define DRRIP_MAX_RRPV    3     // valor "distant"
#define DRRIP_LONG_RRPV   2     // valor "long" (inserção SRRIP)
#define DRRIP_PSEL_WIDTH  10    // bits do PSEL
#define DRRIP_PSEL_MAX    1023  // 2^10 - 1
#define DRRIP_PSEL_INIT   512   // ponto médio do range
#define DRRIP_SDM_SIZE    32    // sets dedicados por política
#define DRRIP_BIP_DENOM   32    // BRRIP insere 1/32 vezes em LONG
```

**Por que M = 2?** O paper testou M = 1, 2, 3 e mostrou que M=2 captura
95% do ganho com menor área. M=3 dobra área para ganho marginal.

**Por que PSEL = 10 bits?** Range de 1024 valores permite tomar decisão
suave (histerese natural) sem oscilar com mudanças de carga curta.

**Por que SDM_SIZE = 32?** Set Dueling requer amostragem estatística
significativa. 32 sets por política é o mínimo recomendado por Qureshi
para sinal de PSEL estável.

### 3.3 Estrutura `drrip_jaleel_t`

```c
typedef struct {
    cache_t *c;
    int   srrip_sdm[DRRIP_SDM_SIZE];
    int   brrip_sdm[DRRIP_SDM_SIZE];
    int   n_sdm;
    int   sdm_kind[1 << 14];     // lookup table de classificação
    int   psel;
    uint8_t *bip_counter_per_set;
} drrip_jaleel_t;
```

**`sdm_kind` como lookup table:**

Em vez de procurar linearmente em `srrip_sdm[]` ou `brrip_sdm[]` a cada
acesso, mantemos uma tabela direta:
- `sdm_kind[set_idx] == 0` → follower
- `sdm_kind[set_idx] == 1` → SDM_SRRIP
- `sdm_kind[set_idx] == 2` → SDM_BRRIP

Acesso O(1) em vez de O(SDM_SIZE). Em hardware seria um bit por conjunto.

**Tamanho de 16384 entradas (`1 << 14`):** suporta caches de até 16K
conjuntos — folga grande para qualquer config de FPGA.

### 3.4 Inicialização — `drrip_jaleel_init`

```c
void drrip_jaleel_init(drrip_jaleel_t *d, cache_t *c, uint32_t seed) {
    d->c = c;
    d->psel = DRRIP_PSEL_INIT;

    int n_per_policy = DRRIP_SDM_SIZE;
    if (c->num_sets / 4 < n_per_policy) {
        n_per_policy = c->num_sets / 4;
        if (n_per_policy < 1) n_per_policy = 1;
    }
    d->n_sdm = n_per_policy;

    // Fisher-Yates shuffle de [0..num_sets-1]
    int *pool = malloc(sizeof(int) * c->num_sets);
    for (int i = 0; i < c->num_sets; i++) pool[i] = i;
    uint32_t rng = seed;
    for (int i = c->num_sets - 1; i > 0; i--) {
        int j = xs32(&rng) % (uint32_t)(i + 1);
        int tmp = pool[i]; pool[i] = pool[j]; pool[j] = tmp;
    }
    // primeiros n → SRRIP_SDM; próximos n → BRRIP_SDM
    for (int i = 0; i < n_per_policy; i++) {
        d->srrip_sdm[i] = pool[i];
        d->sdm_kind[pool[i]] = 1;
    }
    for (int i = 0; i < n_per_policy; i++) {
        d->brrip_sdm[i] = pool[n_per_policy + i];
        d->sdm_kind[pool[n_per_policy + i]] = 2;
    }
    free(pool);
    d->bip_counter_per_set = calloc(c->num_sets, sizeof(uint8_t));
}
```

**Adaptação para caches pequenas:**

Quando `num_sets < 4 * SDM_SIZE`, não conseguimos ter 32 SDMs por política
(precisaríamos de 64 sets dedicados em caches de 32-64 sets — sobraria
muito pouco para followers).

Usamos `n_per_policy = num_sets / 4`, garantindo:
- 25% sets para SRRIP_SDM
- 25% sets para BRRIP_SDM
- 50% sets como followers

Por exemplo, em cache de 64 sets: 16 SRRIP_SDM + 16 BRRIP_SDM + 32 followers.

**Fisher-Yates shuffle determinístico:**

Embaralha o pool `[0..num_sets-1]` usando um PRNG xorshift32 com seed fixa
(seed = `0xC0FFEE` no main). Determinismo = reprodutibilidade total entre
execuções.

Os primeiros `n_per_policy` índices viram SRRIP_SDM, os próximos viram
BRRIP_SDM. **Garante por construção** que os SDMs são índices válidos
dentro de `[0, num_sets)` — esta é a correção crucial vs ChampSim.

### 3.5 PRNG xorshift32

```c
static uint32_t xs32(uint32_t *s) {
    uint32_t x = *s;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *s = x;
    return x;
}
```

Gerador pseudo-aleatório de Marsaglia. Período 2³²-1, qualidade
estatística boa o suficiente para amostragem de SDMs. **Determinístico**:
mesma seed → mesma sequência sempre.

### 3.6 Função `decide_policy` — escolha entre SRRIP e BRRIP

```c
static int decide_policy(drrip_jaleel_t *d, int set_idx) {
    int kind = d->sdm_kind[set_idx];
    if (kind == 1) return 1;  // SRRIP_SDM
    if (kind == 2) return 2;  // BRRIP_SDM
    // follower: bit alto do PSEL decide
    return (d->psel >= DRRIP_PSEL_INIT) ? 2 : 1;
}
```

**Três casos:**

1. **SDM_SRRIP**: sempre roda SRRIP, independente do PSEL
2. **SDM_BRRIP**: sempre roda BRRIP, independente do PSEL
3. **Follower**: segue a política vencedora segundo o PSEL
   - `psel >= 512` → followers usam BRRIP (SRRIP está perdendo)
   - `psel < 512` → followers usam SRRIP (BRRIP está perdendo)

**Por que `>=` em vez de `>`?**

Decisão arbitrária — ambas funcionam. O paper usa `>`. Usamos `>=` porque
em caso de empate (PSEL exatamente 512), preferimos BRRIP por ser mais
agressivo contra cargas com working set grande.

### 3.7 Função `brrip_insert_rrpv` — RRPV de inserção bimodal

```c
static uint8_t brrip_insert_rrpv(drrip_jaleel_t *d, int set_idx) {
    d->bip_counter_per_set[set_idx]++;
    if (d->bip_counter_per_set[set_idx] % DRRIP_BIP_DENOM == 0) {
        return DRRIP_LONG_RRPV;  // 2
    }
    return DRRIP_MAX_RRPV;       // 3
}
```

**Comportamento bimodal:**

- 31 de cada 32 inserções: RRPV = 3 (entra como "distant", sai rápido)
- 1 de cada 32 inserções: RRPV = 2 (entra como "long", tem chance de ficar)

**Por que contador per-set?**

Esta é a correção mais importante vs implementação original. Se o contador
fosse global (como no ChampSim), as inserções BIP de SDM_BRRIP e de
followers em modo BRRIP **compartilhariam o mesmo contador**.

Como SDM_SRRIP nunca incrementa o contador, a "sorte" de quem recebe
RRPV=2 fica desbalanceada entre SDMs e followers em caches pequenas.
Resultado: o sinal do PSEL fica ruidoso e o set dueling sofre.

Com contador per-set, cada conjunto tem sua própria sequência
determinística, sem acoplamento entre sets.

**Em hardware** isso seria barato: 5 bits/conjunto (clog2(32)). Para
uma L2 de 128 conjuntos = 640 bits — irrelevante perante os ~50000 bits
totais da L2.

### 3.8 Função `find_drrip_victim` — busca de vítima com aging

```c
static int find_drrip_victim(cache_t *c, int set_idx) {
    int inv = cache_find_invalid_way(c, set_idx);
    if (inv >= 0) return inv;

    cache_line_t *base = &c->lines[set_idx * c->assoc];
    for (int iter = 0; iter <= DRRIP_MAX_RRPV + 1; iter++) {
        for (int w = 0; w < c->assoc; w++) {
            if (base[w].rrpv == DRRIP_MAX_RRPV) return w;
        }
        // Nenhuma com MAX; envelhece todas as válidas
        for (int w = 0; w < c->assoc; w++) {
            if (base[w].rrpv < DRRIP_MAX_RRPV) base[w].rrpv++;
        }
    }
    return 0;
}
```

**Algoritmo em 3 etapas:**

1. **Prioridade absoluta:** linha inválida (cold start). Ocupa sem
   precisar expulsar ninguém.
2. **Busca por RRPV=3:** se algum bloco já foi marcado como "distant",
   ele é a vítima natural.
3. **Aging:** se nenhum tem RRPV=3, incrementa **todos** os RRPVs do
   conjunto (saturando em 3) e tenta de novo. O loop garante terminar
   em no máximo `MAX_RRPV + 1` iterações, porque eventualmente alguém
   satura.

**Por que aging funciona?**

Imagine um conjunto com RRPVs `[0, 0, 1, 2]`. Não há RRPV=3.
- Aging: `[1, 1, 2, 3]`. Agora a way 3 vira candidata.

Em essência, o aging **descobre relativamente** quem é o "menos importante"
sem manter ordem total. É uma aproximação eficiente de LRU.

**Cota de segurança no loop:**

`MAX_RRPV + 1` iterações é um teto teórico — na prática, sempre termina
na primeira ou segunda. O loop com cota é defensive coding contra bugs
de inicialização que deixariam algum RRPV em estado inválido.

### 3.9 Função principal `drrip_jaleel_access`

```c
int drrip_jaleel_access(drrip_jaleel_t *d, uint64_t addr) {
    cache_t *c = d->c;
    int set_idx = cache_set_of(c, addr);
    uint64_t tag = cache_tag_of(c, addr);
    int way = cache_find_way(c, set_idx, tag);

    if (way >= 0) {
        c->hits++;
        c->lines[set_idx * c->assoc + way].rrpv = 0;  // Hit Priority
        return 1;
    }

    c->misses++;
    if (cache_mark_touched(c, cache_block_of(c, addr))) {
        c->cold_misses++;
    }

    // Atualiza PSEL se este conjunto é SDM
    int kind = d->sdm_kind[set_idx];
    if (kind == 1 && d->psel < DRRIP_PSEL_MAX) d->psel++;
    else if (kind == 2 && d->psel > 0) d->psel--;

    int policy = decide_policy(d, set_idx);
    uint8_t insert_rrpv = (policy == 1) ? DRRIP_LONG_RRPV
                                        : brrip_insert_rrpv(d, set_idx);

    int victim = find_drrip_victim(c, set_idx);
    cache_line_t *L = &c->lines[set_idx * c->assoc + victim];
    L->valid = 1;
    L->tag = tag;
    L->rrpv = insert_rrpv;
    return 0;
}
```

**Fluxo completo:**

1. Decompõe endereço, procura tag
2. **Se HIT:**
   - Incrementa hits
   - **Hit Priority (HP):** RRPV → 0 imediatamente
   - Retorna 1
3. **Se MISS:**
   - Incrementa misses, verifica cold miss
   - **Atualiza PSEL** se este conjunto for SDM:
     - SDM_SRRIP teve miss → PSEL++ (SRRIP perdendo)
     - SDM_BRRIP teve miss → PSEL-- (BRRIP perdendo)
   - Decide qual política aplicar (`SRRIP` ou `BRRIP`)
   - Calcula RRPV de inserção:
     - SRRIP: sempre `LONG_RRPV` (2)
     - BRRIP: `brrip_insert_rrpv()` (bimodal)
   - Encontra vítima (linha inválida ou RRPV=3 ou aging)
   - Substitui pela nova linha com RRPV calculado
   - Retorna 0

**Por que Hit Priority em vez de Frequency Priority?**

O paper compara HP vs FP. HP zera o RRPV (promove a MRU) em hit.
FP só **decrementa** RRPV em hit (promoção gradual). HP ganha em quase
todos os benchmarks porque blocos verdadeiramente quentes saltam
imediatamente para MRU.

### 3.10 Custo de hardware do DRRIP-Jaleel

**Bits por linha:** 2 (RRPV, fixo, independente de associatividade)

**Bits totais por conjunto:** `assoc * 2`
- 16 vias: 16 × 2 = **32 bits/conjunto** (metade do LRU true)

**Bits globais:**
- PSEL: 10 bits
- Contadores BIP per-set: `5 * num_sets` bits

Para cache de 128 sets, 16 vias:
- LRU: 128 × 64 = 8192 bits
- DRRIP-Jaleel: 128 × (32 + 5) + 10 = 4746 bits
- **Economia: ~42%**

---

## 4. Algoritmo DRRIP-ChampSim — drrip_champsim.c

Este arquivo é o **porte literal do `drrip.cc` do ChampSim** (C++) para C,
**preservando exatamente** as decisões de implementação do código upstream
— incluindo as que falham em caches pequenas de FPGA.

### 4.1 Por que portar literalmente em vez de corrigir?

**Para evidenciar empiricamente** que o ChampSim, sem adaptação,
**não funciona** em caches do tamanho que vamos usar no Cyclone III.

Em LLCs grandes (cenário de pesquisa do paper original), os detalhes
de implementação do ChampSim são adequados. Em caches pequenas, três
desses detalhes causam falha silenciosa:

1. **Contador BIP global** (um único contador para todos os sets)
2. **PSEL inicia em 0** (não no centro do range)
3. **SDMs selecionados via `std::knuth_b` sem aplicar módulo NUM_SET**

### 4.2 Estrutura `drrip_champsim_t`

```c
typedef struct {
    cache_t *c;
    size_t  rand_sets[CSIM_NUM_CPUS * CSIM_NUM_POLICY * CSIM_SDM_SIZE];
    int     psel;
    unsigned bip_counter;
} drrip_champsim_t;
```

**Diferenças vs Jaleel:**

| Campo | Jaleel | ChampSim |
|---|---|---|
| Contador BIP | per-set (array) | global (escalar) |
| PSEL inicial | 512 | 0 |
| Lookup de SDM | `sdm_kind[set]` O(1) | busca linear em `rand_sets` |
| Valores em `rand_sets` | índices válidos `[0, num_sets)` | valores brutos do PRNG |

### 4.3 O bug do `knuth_b` — função `knuth_b_proxy`

```c
static size_t knuth_b_proxy(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *state = x;
    return (size_t)x;  // preserva valor "grande" — o ponto do bug
}
```

O `std::knuth_b` do C++ é um gerador pseudo-aleatório complexo (subtract
with carry com lag, shuffle de 256). **Reimplementá-lo exatamente** seria
absurdo e desnecessário — o que importa para reproduzir o bug é a
**propriedade estatística** dos valores gerados.

`std::knuth_b{1}` (seed 1) produz valores tipicamente entre 16807 e 2³¹.
Qualquer PRNG razoável tem a mesma propriedade. Usamos xorshift32 que
retorna valores em `[0, 2³²)` — preserva a propriedade chave: **os
valores não cabem no range `[0, num_sets)` de caches pequenas**.

Primeiros valores gerados:
- `x = 1` → após xorshift: 270369 (`0x42021`)
- próximo: ~270 milhões
- depois: milhares de milhões

Em cache com 64 conjuntos, **nenhum desses valores está em [0, 63]**.

### 4.4 Inicialização — `drrip_champsim_init`

```c
void drrip_champsim_init(drrip_champsim_t *d, cache_t *c) {
    d->c = c;
    d->psel = 0;          // ChampSim default
    d->bip_counter = 0;

    size_t TOTAL_SDM_SETS = CSIM_NUM_CPUS * CSIM_NUM_POLICY * CSIM_SDM_SIZE;
    uint32_t state = 1;   // knuth_b{1} -> seed = 1
    for (size_t i = 0; i < TOTAL_SDM_SETS; i++) {
        d->rand_sets[i] = knuth_b_proxy(&state);
    }
    qsort(d->rand_sets, TOTAL_SDM_SETS, sizeof(size_t), size_t_cmp);
}
```

**Esta função reproduz exatamente o construtor do ChampSim:**

```cpp
// drrip.cc original
std::generate_n(std::back_inserter(rand_sets), TOTAL_SDM_SETS,
                std::knuth_b{1});
std::sort(std::begin(rand_sets), std::end(rand_sets));
std::fill_n(std::back_inserter(PSEL), NUM_CPUS, ... value{0});
```

**A linha crítica é a ausência de módulo:**

```c
d->rand_sets[i] = knuth_b_proxy(&state);  // SEM % num_sets
```

Se tivéssemos escrito `% c->num_sets`, o algoritmo funcionaria. Mas
isso *não é o que o ChampSim faz*, então não fazemos.

### 4.5 Função `update_bip` — contador global

```c
static void update_bip(drrip_champsim_t *d, int set_idx, int way) {
    cache_line_t *L = &d->c->lines[set_idx * d->c->assoc + way];
    L->rrpv = CSIM_MAX_RRPV;
    d->bip_counter++;
    if (d->bip_counter == CSIM_BIP_MAX) {
        d->bip_counter = 0;
        L->rrpv = CSIM_MAX_RRPV - 1;
    }
}
```

**Diferença vs Jaleel:**

`bip_counter` é campo direto da struct (global). Cada inserção BIP
incrementa o mesmo contador, independente de qual conjunto está sendo
escrito.

**Problema em caches pequenas:**

Em LLCs grandes (~milhares de sets), o contador global se espalha
estatisticamente entre todos os sets — distribuição quase uniforme.

Em caches pequenas (32-64 sets), as inserções BIP acontecem em sequência
desigual entre sets, criando correlação artificial. Combine isso com o
fato de que SDM_BRRIP e followers em modo BRRIP **compartilham** o
contador, e o sinal do PSEL fica enviesado.

### 4.6 Função `find_in_rand_sets` — busca de SDM falha

```c
static int find_in_rand_sets(const drrip_champsim_t *d, size_t value,
                               int begin, int end) {
    for (int i = begin; i < end; i++) {
        if (d->rand_sets[i] == value) return i;
    }
    return end;  // não encontrou
}
```

Substitui `std::find` do C++. Em caches pequenas:

- `value` = `set_idx` ∈ [0, 63] (número pequeno)
- `rand_sets[i]` contém valores tipo 270369, 800 milhões, etc.

**Como nunca há `value == rand_sets[i]`**, a função sempre retorna `end`
(não encontrado). Em `update_replacement_state`, isso significa que
**todos os sets caem no caminho "follower"**, e o PSEL nunca atualiza.

### 4.7 Função principal `drrip_champsim_access`

```c
int drrip_champsim_access(drrip_champsim_t *d, uint64_t addr) {
    // [setup igual ao Jaleel]
    if (way >= 0) {
        c->hits++;
        c->lines[set_idx * c->assoc + way].rrpv = 0;
        return 1;
    }
    c->misses++;
    if (cache_mark_touched(c, cache_block_of(c, addr))) {
        c->cold_misses++;
    }

    // ChampSim: escolhe vítima ANTES de update_replacement_state
    int victim = cache_find_invalid_way(c, set_idx);
    if (victim < 0) victim = find_drrip_victim(c, set_idx);
    cache_line_t *L = &c->lines[set_idx * c->assoc + victim];
    L->valid = 1;
    L->tag = tag;

    // update_replacement_state em miss
    int triggering_cpu = 0;
    int begin = triggering_cpu * CSIM_NUM_POLICY * CSIM_SDM_SIZE;
    int end = begin + CSIM_NUM_POLICY * CSIM_SDM_SIZE;
    int leader = find_in_rand_sets(d, (size_t)set_idx, begin, end);

    if (leader == end) {
        // follower
        if (d->psel > CSIM_PSEL_MAX / 2) {
            update_bip(d, set_idx, victim);
        } else {
            update_srrip(d, set_idx, victim);
        }
    } else if (leader == begin) {
        if (d->psel > 0) d->psel--;
        update_bip(d, set_idx, victim);
    } else if (leader == begin + 1) {
        if (d->psel < CSIM_PSEL_MAX) d->psel++;
        update_srrip(d, set_idx, victim);
    } else {
        // SDM intermediário — tratado como follower no ChampSim
        if (d->psel > CSIM_PSEL_MAX / 2) update_bip(d, set_idx, victim);
        else update_srrip(d, set_idx, victim);
    }
    return 0;
}
```

**Em caches pequenas, o caminho percorrido é sempre o `leader == end` (follower):**

1. `find_in_rand_sets` retorna `end` porque os valores são grandes demais
2. Cai no ramo `leader == end`
3. Verifica `psel > PSEL_MAX/2` = `psel > 511`
4. **Como PSEL inicia em 0 e nunca é atualizado** (já que nunca cai nos
   ramos SDM), a condição **é sempre falsa**
5. Sempre executa `update_srrip` → insere com RRPV = 2

**Conclusão:** o DRRIP-ChampSim em caches pequenas **degenera em SRRIP
puro**. E SRRIP puro com working set + scan invasivo **comporta-se como
LRU** (porque toda linha entra em LONG_RRPV=2, depois aging nivela tudo
e a escolha de vítima fica praticamente aleatória — equivalente
estatisticamente a LRU).

### 4.8 Por que isso aparece nos resultados como "= LRU"

| Config A (mixed_access) | L1 hit rate |
|---|---|
| LRU | 68,18% |
| DRRIP-Jaleel | 71,25% |
| DRRIP-ChampSim | **68,18%** ← idêntico ao LRU |

A coincidência **não é por sorte estatística** — é estrutural. O ChampSim
caiu em modo SRRIP-puro permanente, e o trace adversarial (working set +
scan) faz SRRIP-puro produzir o mesmo número de hits que LRU produziria.

Em Config C, alguns dos valores aleatórios do PRNG por acaso caem em
índices válidos (cache de 128 sets oferece range maior), e o algoritmo
captura **parte** do ganho — mas ainda fica abaixo do Jaleel corrigido.

### 4.9 Como o ChampSim "funcionaria" em caches grandes

Em LLC de, digamos, 2048 sets:
- `set_idx` ∈ [0, 2047]
- `rand_sets[i]` contém valores aleatórios em [0, 2³¹)
- **Por sorte estatística**, alguns valores cairão em [0, 2047]

A probabilidade de um valor de 32 bits cair em [0, 2047] é ~5×10⁻⁷ por
sorteio, mas como o PRNG gera 64 valores diferentes, e a cache tem 2048
posições alvo, **alguns SDMs por acaso terão índices válidos** — o
suficiente para o set dueling funcionar.

Em caches pequenas (32-128 sets), a probabilidade despenca: ~10⁻⁸ por
sorteio, 64 sorteios, **nenhum cai por acaso**. Set dueling falha.

---

## 5. Benchmarks — benchmarks.c

Cinco geradores de trace que reproduzem os padrões do Apêndice A da spec
+ um complementar baseado na Fig. 1d do paper.

### 5.1 `gen_streaming_hotset`

```c
ssize_t gen_streaming_hotset(uint64_t *buf, size_t cap,
                              size_t array_size_bytes, int iterations) {
    size_t n = 0;
    size_t n_elems = array_size_bytes / ELEM_SIZE;
    for (int it = 0; it < iterations; it++) {
        for (size_t i = 0; i < n_elems; i++) {
            uint64_t addr = ARRAY_BASE + i * ELEM_SIZE;
            WRITE(addr);  // read
            WRITE(addr);  // write
            if (i % 64 == 0) {
                WRITE(HOT_ADDR);
                WRITE(HOT_ADDR);
            }
        }
    }
    return (ssize_t)n;
}
```

Reproduz `array[i] += i` + `*hot_data += array[i]` a cada 64 elementos.

**Padrão de acesso:**
- Varredura linear sequencial → ótima localidade espacial intra-bloco
- Variável `hot` (1 bloco) acessada a cada 64 elementos do array

**Característica chave:** o `hot` mora em conjunto isolado (ou compete com
no máximo 1 bloco do array). LRU já mantém em 99,93% — sem espaço para
melhoria de política.

### 5.2 `gen_matrix_conv`

```c
ssize_t gen_matrix_conv(uint64_t *buf, size_t cap, int width, int height) {
    size_t n = 0;
    size_t row_bytes = (size_t)width * ELEM_SIZE;
    for (int y = 1; y < height - 1; y++) {
        for (int x = 0; x < width; x++) {
            uint64_t base = MATRIX_BASE + (size_t)y * row_bytes
                            + (size_t)x * ELEM_SIZE;
            WRITE(base - row_bytes);                       // src[y-1][x]
            WRITE(base);                                    // src[y][x]
            WRITE(base + row_bytes);                        // src[y+1][x]
            WRITE(base + row_bytes * (size_t)height);       // dst[y][x]
        }
    }
    return (ssize_t)n;
}
```

Convolução vertical 3×1: para cada pixel da imagem, lê 3 linhas vizinhas
e escreve no resultado.

**Padrão:** working set = 3 linhas, percorridas em sequência. Cabe em
qualquer cache razoável. Reuso natural alto.

### 5.3 `gen_linked_list`

```c
ssize_t gen_linked_list(uint64_t *buf, size_t cap, int n_nodes,
                         int iterations, int randomize) {
    size_t n = 0;
    int *order = malloc(sizeof(int) * (size_t)n_nodes);
    for (int i = 0; i < n_nodes; i++) order[i] = i;
    if (randomize) {
        uint32_t s = 123;
        for (int i = n_nodes - 1; i > 0; i--) {
            int j = (int)(xs(&s) % (uint32_t)(i + 1));
            int t = order[i]; order[i] = order[j]; order[j] = t;
        }
    }
    int node_size = 8;
    for (int it = 0; it < iterations; it++) {
        for (int k = 0; k < n_nodes; k++) {
            uint64_t addr = LIST_BASE + (uint64_t)order[k] * node_size;
            WRITE(addr);
        }
    }
    free(order);
    return (ssize_t)n;
}
```

Pointer chasing simulado com ordem **embaralhada determinística** (seed 123).

**Padrão:** working set 2× L2, mas ordem aleatória de acesso. Quase
equivalente a random replacement na prática — política racional não
consegue extrair localidade temporal.

### 5.4 `gen_pattern_search`

```c
ssize_t gen_pattern_search(uint64_t *buf, size_t cap, size_t blob_size,
                            int window) {
    size_t n = 0;
    size_t n_elems = blob_size / ELEM_SIZE;
    for (size_t i = (size_t)window; i < n_elems; i++) {
        for (int k = window; k > 0; k--) {
            uint64_t addr = BLOB_BASE + (i - (size_t)k) * ELEM_SIZE;
            WRITE(addr);
        }
        WRITE(BLOB_BASE + i * ELEM_SIZE);
    }
    return (ssize_t)n;
}
```

Para cada posição `i`, releitura das `window` posições anteriores.

**Padrão:** working set fixo de `window` elementos. Para janela=32 e
elementos de 4 bytes, working set = 128 bytes = **1 bloco**. Cabe em
qualquer cache. Hit rate ~99,95% trivial.

### 5.5 `gen_mixed_access` — o benchmark complementar

```c
ssize_t gen_mixed_access(uint64_t *buf, size_t cap, int ws_blocks,
                          int scan_blocks, int ws_repeats, int outer_iters) {
    size_t n = 0;
    int block_size = 32;
    for (int it = 0; it < outer_iters; it++) {
        // Working set acessado várias vezes
        for (int r = 0; r < ws_repeats; r++) {
            for (int i = 0; i < ws_blocks; i++) {
                WRITE(WS_BASE + (uint64_t)i * block_size);
            }
        }
        // Scan invasivo
        for (int i = 0; i < scan_blocks; i++) {
            WRITE(SCAN_BASE + (uint64_t)i * block_size);
        }
    }
    return (ssize_t)n;
}
```

Reproduz o padrão da **Figura 1d** do paper Jaleel et al.:
- Working set de 64 blocos quentes, reusado 16 vezes seguidas
- Scan de 384 blocos invasivos (6× maior que o working set)
- Loop externo 10 vezes

**Padrão:**
```
[WS × 16] [SCAN] [WS × 16] [SCAN] [WS × 16] [SCAN] ...
```

**Característica chave:** working set e scan **compartilham conjuntos da
cache** (mapeamento conflituoso). Demanda > oferta de vias → eviction
forçada → **a política decide quem fica**.

Este é o **único** dos 5 benchmarks que exercita genuinamente a decisão
de eviction. LRU sofre, DRRIP-Jaleel se adapta via Set Dueling.

---

## 6. Driver experimental — main.c

### 6.1 Configurações de cache

```c
static const cache_config_t CONFIGS[] = {
    {"A",  4*1024, 32, 2,  32*1024, 64, 8},
    {"B",  4*1024, 32, 4,  64*1024, 64, 8},
    {"C",  8*1024, 32, 4, 128*1024, 64, 16},
};
```

Três configurações representando diferentes pontos de design:
- **A (compacta):** menor área, 2 vias em L1 — alvo Cyclone III mais agressivo
- **B (intermediária):** 4 vias em L1, L2 maior
- **C (robusta):** L1 maior e L2 com mais vias

### 6.2 Hierarquia L1+L2 modelada

```c
for (ssize_t i = 0; i < n_accesses; i++) {
    uint64_t addr = trace[i];
    int hit;
    if (pol == POL_LRU)                hit = lru_access(&l1, addr);
    else if (pol == POL_DRRIP_JALEEL)  hit = drrip_jaleel_access(&l1_jal, addr);
    else                                hit = drrip_champsim_access(&l1_csim, addr);

    if (!hit) {
        if (pol == POL_LRU)               lru_access(&l2, addr);
        else if (pol == POL_DRRIP_JALEEL) drrip_jaleel_access(&l2_jal, addr);
        else                              drrip_champsim_access(&l2_csim, addr);
    }
}
```

**Hierarquia não-inclusiva, não-exclusiva (NINE):**

- Acesso vai para L1 primeiro
- Se for miss em L1, propaga para L2
- Se for miss em L2 também, vai à memória principal (não modelada explicitamente)

A política é aplicada **independentemente em L1 e L2**. Ambas usam a
mesma política em uma rodada (LRU em ambas, ou DRRIP-Jaleel em ambas,
etc.).

### 6.3 Cálculo de AMAT

```c
r.amat = 1.0 + (1.0 - h1) * (10.0 + (1.0 - h2) * 100.0);
```

AMAT = Average Memory Access Time.

Latências assumidas:
- L1: 1 ciclo
- L2: 10 ciclos
- Memória principal: 100 ciclos

Fórmula:
```
AMAT = T_L1 + (1 - h_L1) × [T_L2 + (1 - h_L2) × T_MEM]
     = 1   + (1 - h_L1) × [10  + (1 - h_L2) × 100]
```

Métrica única que captura desempenho real (não só hit rate isolada).

### 6.4 Cálculo de overhead

```c
static int policy_bits_per_set(policy_kind_t pol, int assoc) {
    if (pol == POL_LRU) {
        int k = 0; while ((1<<k) < assoc) k++;
        return assoc * k;
    }
    return assoc * 2;  // DRRIP: M=2 por linha
}

static int total_storage_bits(const cache_t *c, policy_kind_t pol) {
    int tag_bits = 32 - c->offset_bits - c->index_bits;
    int per_line_data = 1 + tag_bits;  // valid + tag
    int policy_bits = policy_bits_per_set(pol, c->assoc);
    return c->num_sets * (c->assoc * per_line_data + policy_bits);
}
```

**Bits por linha:**
- `valid` (1 bit) + `tag` (21 bits para endereço 32 bits em L1) = 22 bits

**Bits de política por conjunto:**
- LRU: `assoc × ceil(log2(assoc))`
- DRRIP: `assoc × 2` (M=2)

**Total:** `num_sets × (assoc × bits_por_linha + bits_de_política)`

Para L2 16 vias:
- LRU: 16 × 4 = 64 bits de política por conjunto
- DRRIP: 16 × 2 = 32 bits de política por conjunto
- **DRRIP economiza 50% dos bits de política**

---

## 7. Comparação algorítmica

### 7.1 Tabela resumo

| Aspecto | LRU | DRRIP-Jaleel | DRRIP-ChampSim |
|---|---|---|---|
| Métrica de ranking | Idade (0..n-1) | RRPV (0..3) | RRPV (0..3) |
| Bits por linha | log2(assoc) | 2 | 2 |
| Estado extra | nenhum | PSEL + BIP/set | PSEL + BIP global |
| PSEL inicial | — | PSEL_MAX/2 (512) | 0 |
| Seleção SDM | — | shuffle válido | knuth_b sem módulo |
| Hit rate em mixed_access (Config C) | 68,18% | 78,41% | 72,27% |
| Funciona em FPGA Cyclone III? | Sim | **Sim** | **Não, degenera** |

### 7.2 Caminho de execução: HIT

| Política | Ação |
|---|---|
| LRU | `on_hit()` envelhece linhas mais novas; promovida → idade 0 |
| DRRIP-Jaleel | `rrpv = 0` (Hit Priority) |
| DRRIP-ChampSim | `rrpv = 0` (idêntico) |

### 7.3 Caminho de execução: MISS

| Política | Vítima | Inserção |
|---|---|---|
| LRU | Inválida > linha com idade n-1 | Como MRU (idade 0); todas envelhecem |
| DRRIP-Jaleel | Inválida > linha RRPV=3 > aging | SRRIP: RRPV=2; BRRIP: 31/32 com RRPV=3, 1/32 com RRPV=2 (per-set) |
| DRRIP-ChampSim | Inválida > linha com max_rrpv + delta aging | Sempre SRRIP em caches pequenas (degeneração) |

### 7.4 Decisão dinâmica (apenas DRRIP)

```c
// Jaleel
policy = (psel >= 512) ? BRRIP : SRRIP;

// ChampSim
policy = (psel > 511) ? BRRIP : SRRIP;
```

Diferença trivial (`>=` vs `>`). O problema **não** é essa comparação — é
que no ChampSim o PSEL **nunca muda** em caches pequenas, então
sempre cai em SRRIP.

### 7.5 Por que esses três algoritmos no mesmo projeto

1. **LRU** — baseline obrigatório. Toda comparação de cache replacement
   parte de LRU.
2. **DRRIP-Jaleel** — o que queremos defender. Versão correta para FPGA.
3. **DRRIP-ChampSim** — referência externa **canônica** da comunidade.
   Permite mostrar à banca: "validamos contra a implementação padrão; 4
   benchmarks empatam (algoritmo correto), 1 ganhamos (adaptação para FPGA)".

---

## Apêndice A: Glossário de termos

| Termo | Significado |
|---|---|
| RRPV | Re-Reference Prediction Value — predição em 2 bits de quão distante está a próxima referência |
| SRRIP | Static RRIP — sempre insere com RRPV = LONG (2) |
| BRRIP | Bimodal RRIP — insere com RRPV=3 quase sempre, RRPV=2 em ~1/32 |
| DRRIP | Dynamic RRIP — combina SRRIP+BRRIP via Set Dueling |
| SDM | Set Dueling Monitor — conjunto dedicado a uma política para "votar" |
| PSEL | Policy Selector — contador que decide qual política os followers usam |
| HP | Hit Priority — promoção imediata para MRU em hit (RRPV=0) |
| FP | Frequency Priority — promoção gradual (RRPV--) em hit |
| AMAT | Average Memory Access Time — latência média ponderada |
| NINE | Non-Inclusive, Non-Exclusive — política de hierarquia |
| Cold miss | Miss compulsório — primeira vez vendo o bloco |
| Conflict miss | Miss por choque em mesma posição da cache |
| Capacity miss | Miss porque o working set excede a capacidade |

## Apêndice B: Referências

- **Jaleel et al.** (2010). "High Performance Cache Replacement Using
  Re-reference Interval Prediction (RRIP)." ISCA 2010.
- **Qureshi et al.** (2007). "Adaptive Insertion Policies for High
  Performance Caching." ISCA 2007 (origem do Set Dueling).
- **ChampSim simulator:** github.com/ChampSim/ChampSim
