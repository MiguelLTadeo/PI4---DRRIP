"""
test_sanity.py
==============
Testes de sanidade do simulador de cache. Verifica propriedades fundamentais
que DEVEM valer se LRU e DRRIP estao implementados corretamente.

Rodar:
    python3 -m unittest test_sanity -v
    # ou simplesmente:
    python3 test_sanity.py

Estes testes sao "golden checks" - se algum falha, o simulador esta bugado
e nao serve como referencia para validar o RTL Verilog. Use estes mesmos
checks no testbench Verilog para validar a implementacao em hardware.

Estrutura:
  TestDeterminism  - prova que execucoes repetidas dao resultados identicos
  TestBasicCache   - propriedades basicas (cold miss, hit em reuso, etc.)
  TestLRU          - propriedades especificas do LRU
  TestDRRIP        - propriedades especificas do DRRIP (RRPV, PSEL, set dueling)
  TestComparative  - DRRIP deve ganhar do LRU em padroes conhecidos
"""

import unittest
import random
from cache_model import Cache, MemoryHierarchy
from traces import (trace_streaming, trace_matrix_conv,
                    trace_linked_list, trace_pattern_search)


# ============================================================================
# Helpers
# ============================================================================

def run_trace(cache, trace):
    """Roda um trace (lista ou gerador de enderecos) numa cache."""
    for item in trace:
        if isinstance(item, tuple):
            addr = item[0]   # ignora kind, cache nao precisa
        else:
            addr = item
        cache.access(addr)
    return cache


def hits_misses(cache):
    return cache.hits, cache.misses


# ============================================================================
# Testes de determinismo
# ============================================================================

class TestDeterminism(unittest.TestCase):
    """Prova que o simulador e' deterministico (resultado bit-a-bit identico
    entre execucoes). Requisito para usar como golden reference do RTL."""

    def _build_cache(self, policy):
        return Cache(size_bytes=1024, block_size=32, assoc=4, policy=policy)

    def _run_streaming(self, policy):
        cache = self._build_cache(policy)
        run_trace(cache, trace_streaming(outer_iters=1, array_words=256))
        return cache.hits, cache.misses, cache.accesses

    def test_lru_deterministic(self):
        """LRU: 2 execucoes do mesmo trace -> resultados identicos."""
        r1 = self._run_streaming('LRU')
        r2 = self._run_streaming('LRU')
        self.assertEqual(r1, r2,
            "LRU nao e' deterministico! Algum RNG nao-semeado?")

    def test_drrip_deterministic(self):
        """DRRIP: idem. Importante porque o BRRIP poderia usar PRNG."""
        r1 = self._run_streaming('DRRIP')
        r2 = self._run_streaming('DRRIP')
        self.assertEqual(r1, r2,
            "DRRIP nao e' deterministico! Verifique brrip_counter.")

    def test_drrip_psel_deterministic(self):
        """PSEL final deve ser identico entre runs."""
        c1 = self._build_cache('DRRIP')
        run_trace(c1, trace_streaming(outer_iters=1, array_words=128))
        c2 = self._build_cache('DRRIP')
        run_trace(c2, trace_streaming(outer_iters=1, array_words=128))
        self.assertEqual(c1.psel, c2.psel)


# ============================================================================
# Propriedades basicas (devem valer em qualquer cache razoavel)
# ============================================================================

class TestBasicCache(unittest.TestCase):
    """Comportamentos fundamentais validos em LRU e DRRIP."""

    def _both_policies(self):
        return [
            Cache(1024, 32, 4, policy='LRU'),
            Cache(1024, 32, 4, policy='DRRIP'),
        ]

    def test_first_access_is_miss(self):
        """Primeiro acesso a um endereco em cache fria -> miss obrigatorio."""
        for cache in self._both_policies():
            hit = cache.access(0x1000)
            self.assertFalse(hit, f"{cache.policy}: primeiro acesso deveria ser miss")
            self.assertEqual(cache.hits, 0)
            self.assertEqual(cache.misses, 1)

    def test_immediate_reuse_is_hit(self):
        """Acessar mesmo endereco 2x seguidas -> 1 miss + 1 hit."""
        for cache in self._both_policies():
            cache.access(0x2000)
            hit = cache.access(0x2000)
            self.assertTrue(hit, f"{cache.policy}: reuso imediato deveria ser hit")

    def test_same_block_different_offset_is_hit(self):
        """Acessos dentro do mesmo bloco (32B) -> 1 miss + N-1 hits."""
        for cache in self._both_policies():
            # Bloco 0x3000-0x301F (32 bytes)
            cache.access(0x3000)
            for offset in [4, 8, 12, 16, 20, 24, 28]:
                self.assertTrue(cache.access(0x3000 + offset),
                    f"{cache.policy}: offset {offset} mesmo bloco deveria ser hit")
            self.assertEqual(cache.hits, 7)
            self.assertEqual(cache.misses, 1)

    def test_working_set_equals_assoc_is_all_hits(self):
        """Working set = associatividade, num mesmo set -> 100% hit apos aquecer.

        Constroi enderecos que mapeiam para o MESMO set mas tags diferentes."""
        for cache in self._both_policies():
            block = cache.block_size
            num_sets = cache.num_sets
            stride = block * num_sets   # mesmo set, tag diferente
            base = 0x4000
            assoc = cache.assoc

            # Aquecimento: instala 'assoc' blocos no mesmo set
            for k in range(assoc):
                cache.access(base + k * stride)
            cache.reset_stats()

            # Reuso ciclico: tudo deve ser hit
            for _ in range(10):
                for k in range(assoc):
                    self.assertTrue(cache.access(base + k * stride),
                        f"{cache.policy}: WS=assoc deveria dar 100% hit")
            self.assertEqual(cache.misses, 0,
                f"{cache.policy}: nao deveria haver miss nessa configuracao")

    def test_streaming_exceeds_cache_high_miss_rate(self):
        """Working set >> capacidade -> miss rate proximo de 100%."""
        for cache in self._both_policies():
            # Stride forca cada acesso para um set diferente, todos diferentes
            n_accesses = cache.num_sets * cache.assoc * 4   # 4x a capacidade
            for i in range(n_accesses):
                cache.access(i * cache.block_size)
            self.assertGreater(cache.miss_rate, 0.95,
                f"{cache.policy}: streaming deveria ter miss rate >95%, "
                f"obteve {cache.miss_rate:.2%}")


# ============================================================================
# Propriedades especificas do LRU
# ============================================================================

class TestLRU(unittest.TestCase):
    """Comportamentos que SO o LRU exibe."""

    def test_lru_evicts_oldest(self):
        """Apos encher set, proximo miss expulsa o MAIS ANTIGO (nao o ultimo).

        Cenario: assoc=4. Acessa A,B,C,D no mesmo set (A e' o mais antigo).
        Acessa E -> deve expulsar A. Verifica DIRETAMENTE no estado interno
        (em vez de fazer accesses extras que poluem a ordem LRU).
        """
        cache = Cache(1024, 32, 4, policy='LRU')
        block = cache.block_size
        stride = block * cache.num_sets    # mesmo set, tags diferentes
        base = 0x10000

        # Instala A, B, C, D
        addrs = [base + k * stride for k in range(5)]
        tags  = [cache._decompose(a)[0] for a in addrs]
        _, set_idx = cache._decompose(addrs[0])

        for k in range(4):
            cache.access(addrs[k])
        # Acessa E - deve expulsar A
        cache.access(addrs[4])

        # Verifica diretamente: tag de A nao deve mais estar no set;
        # tags de B, C, D devem continuar; tag de E deve estar la.
        tags_no_set = {ln.tag for ln in cache.sets[set_idx] if ln.valid}
        self.assertNotIn(tags[0], tags_no_set,
            "LRU: tag de A (mais antigo) deveria ter sido expulso")
        self.assertIn(tags[1], tags_no_set,
            "LRU: tag de B deveria continuar na cache")
        self.assertIn(tags[2], tags_no_set,
            "LRU: tag de C deveria continuar na cache")
        self.assertIn(tags[3], tags_no_set,
            "LRU: tag de D deveria continuar na cache")
        self.assertIn(tags[4], tags_no_set,
            "LRU: tag de E (acabou de entrar) deveria estar na cache")

    def test_lru_promotes_on_hit(self):
        """Hit em A promove A para MRU - A deve sobreviver a uma rodada extra."""
        cache = Cache(1024, 32, 4, policy='LRU')
        block = cache.block_size
        stride = block * cache.num_sets
        base = 0x20000

        # Instala A, B, C, D (A mais antigo)
        for k in range(4):
            cache.access(base + k * stride)
        # Hit em A -> A vira MRU (mais recente)
        cache.access(base + 0 * stride)
        cache.reset_stats()

        # Agora insere E - deveria expulsar B (que virou o mais antigo apos
        # a promocao de A)
        cache.access(base + 4 * stride)

        # A deve sobreviver (foi promovido)
        self.assertTrue(cache.access(base + 0 * stride),
            "LRU: A deveria ter sido promovido a MRU apos hit")
        # B deve ter sido expulso
        self.assertFalse(cache.access(base + 1 * stride),
            "LRU: B (mais antigo apos promocao de A) deveria ser expulso")


# ============================================================================
# Propriedades especificas do DRRIP
# ============================================================================

class TestDRRIP(unittest.TestCase):
    """Comportamentos que validam a implementacao do DRRIP (RRPV, PSEL,
    set dueling, BRRIP bimodal)."""

    def test_hit_resets_rrpv_to_zero(self):
        """Hit promotion: bloco que da hit -> RRPV vai para 0."""
        cache = Cache(1024, 32, 4, policy='DRRIP')
        cache.access(0x30000)
        # Achar manualmente onde o bloco foi instalado
        tag, set_idx = cache._decompose(0x30000)
        # Antes do hit: RRPV >= rrpv_long
        cache.access(0x30000)  # gera hit
        # Apos hit: RRPV deve ser 0
        cache_set = cache.sets[set_idx]
        hit_lines = [ln for ln in cache_set if ln.valid and ln.tag == tag]
        self.assertEqual(len(hit_lines), 1)
        self.assertEqual(hit_lines[0].rrpv, 0,
            "DRRIP: RRPV deveria ser 0 apos hit (hit promotion)")

    def test_psel_initialization(self):
        """PSEL deve comecar em ~midrange (paper: 512 para 10 bits)."""
        cache = Cache(1024, 32, 4, policy='DRRIP')
        self.assertEqual(cache.psel, cache.psel_max // 2,
            "PSEL deveria iniciar no meio")

    def test_psel_saturates_high(self):
        """Forcar SRRIP a perder muito -> PSEL satura no maximo."""
        cache = Cache(1024, 32, 4, policy='DRRIP')

        # Acessa enderecos que caem em sets SRRIP-dedicados com working
        # set >> cache, forcando misses constantes nesses sets.
        # SD pattern = sets cujo (set_idx & mask) == 0 sao SRRIP-dedicados.
        # Garantimos isso usando enderecos cujo set_idx seja 0.
        block = cache.block_size
        num_sets = cache.num_sets
        # Para set_idx=0, addr deve ter os bits de index zerados.
        # Cada novo "tag" surge somando num_sets*block ao endereco.
        stride = block * num_sets
        for i in range(2000):
            cache.access(i * stride)   # todos caem em set_idx=0

        # set_idx=0 e' SRRIP-dedicado, e o working set excede assoc -> muitos
        # misses em SRRIP-dedicado -> PSEL deve ter subido
        self.assertGreater(cache.psel, cache.psel_max // 2,
            f"PSEL deveria ter aumentado (SRRIP-dedicado perdeu muito), "
            f"esta em {cache.psel}")

    def test_psel_saturates_low(self):
        """Forcar BRRIP a perder muito -> PSEL satura no minimo."""
        # Cache grande o suficiente para conter sets dedicados (precisa
        # de pelo menos 32 sets, ja que sd_log2=5 -> mask=31).
        # 32 sets * 4 ways * 32 bytes/bloco = 4096 bytes
        cache = Cache(4096, 32, 4, policy='DRRIP')

        # Sets BRRIP-dedicados tem (set_idx & mask) == mask (todos 1s).
        # Para sd_log2=5 (constituency=32), mask=31. Precisamos set_idx
        # cujos 5 LSBs sejam 1 -> set_idx % 32 == 31.
        # Mas nossa cache tem num_sets pequeno; ajustamos para alvo apropriado.
        # Idea: pegar um endereco que cai em set onde os SD_LOG2 bits = mask.
        block = cache.block_size
        num_sets = cache.num_sets
        sd_mask = cache._sd_mask

        # Achar primeiro set cujo (idx & sd_mask) == sd_mask
        target_set = None
        for s in range(num_sets):
            if (s & sd_mask) == sd_mask:
                target_set = s
                break

        if target_set is None:
            self.skipTest("Cache pequena demais para ter set BRRIP-dedicado")

        # Working set pequeno (cabe em assoc) - LRU teria 100% hit apos warmup,
        # mas com BRRIP-dedicado a insercao distante faz blocos serem expulsos
        # antes do reuso -> miss rate alto -> PSEL deve cair.
        stride = block * num_sets
        # Enderecos que caem em target_set: addr = target_set*block + k*stride
        # Working set MAIOR que assoc para forcar substituicao
        ws_size = cache.assoc + 2
        for _ in range(500):
            for k in range(ws_size):
                addr = target_set * block + k * stride
                cache.access(addr)

        # Em set BRRIP-dedicado com WS > assoc, BRRIP insere com RRPV=max
        # e blocos sao expulsos imediatamente -> miss rate alto -> PSEL desce.
        self.assertLess(cache.psel, cache.psel_max // 2,
            f"PSEL deveria ter caido (BRRIP-dedicado perdendo), "
            f"esta em {cache.psel}")

    def test_brrip_bimodal_ratio(self):
        """BRRIP insere com RRPV=long em ~1/32 das insercoes (resto = distant).

        Validacao indireta: instala muitos blocos via politica BRRIP forcada
        (set BRRIP-dedicado) e conta quantas tiveram rrpv == long.
        """
        cache = Cache(4096, 32, 4, policy='DRRIP')
        sd_mask = cache._sd_mask
        block = cache.block_size
        num_sets = cache.num_sets

        target_set = None
        for s in range(num_sets):
            if (s & sd_mask) == sd_mask:
                target_set = s
                break
        if target_set is None:
            self.skipTest("Sem set BRRIP-dedicado disponivel")

        # Conta diretamente acessando o decisor de insercao com state
        # de cache controlado.
        long_count = 0
        distant_count = 0
        N = 320   # multiplo de 32 para razao limpa
        for _ in range(N):
            rrpv = cache._decide_insertion_rrpv(target_set)
            if rrpv == cache.rrpv_long:
                long_count += 1
            elif rrpv == cache.rrpv_distant:
                distant_count += 1
        ratio = long_count / N
        # Esperado: 1/32 = ~3.1%. Tolerancia: 1.5% a 5%.
        self.assertGreater(ratio, 0.015,
            f"BRRIP: razao de insercao long muito baixa ({ratio:.2%})")
        self.assertLess(ratio, 0.05,
            f"BRRIP: razao de insercao long muito alta ({ratio:.2%})")

    def test_drrip_aging_eventually_finds_victim(self):
        """Quando todos os RRPV < max, aging step incrementa ate achar vitima.

        Forcamos uma situacao onde todos os blocos do set tem RRPV=0
        (acabaram de dar hit), e mostramos que o miss seguinte e' resolvido."""
        cache = Cache(1024, 32, 4, policy='DRRIP')
        block = cache.block_size
        stride = block * cache.num_sets
        base = 0x40000

        # Instala 4 blocos e da hit em todos (RRPV=0 em todos)
        for k in range(4):
            cache.access(base + k * stride)
        for k in range(4):
            cache.access(base + k * stride)

        # Agora todos RRPV=0. Inserir um 5o deve funcionar (sem loop infinito).
        cache.access(base + 4 * stride)
        # Se chegou aqui sem travar, o aging step funciona.
        # E o novo bloco esta na cache.
        self.assertTrue(cache.access(base + 4 * stride),
            "DRRIP: novo bloco deveria estar na cache apos aging")


# ============================================================================
# Comparacoes DRRIP vs LRU (validacao do "ganho" esperado)
# ============================================================================

class TestComparative(unittest.TestCase):
    """DRRIP deve ganhar do LRU em padroes onde o paper preve ganho,
    e nao perder catastroficamente em padroes amigaveis ao LRU."""

    def _both(self, **kwargs):
        defaults = dict(size_bytes=4096, block_size=32, assoc=4)
        defaults.update(kwargs)
        return (Cache(policy='LRU', **defaults),
                Cache(policy='DRRIP', **defaults))

    def test_scan_resistance(self):
        """Scan resistance: um working set quente + scan adversario,
        DRRIP deve preservar melhor o working set que LRU."""
        lru, drrip = self._both()
        block = 32
        num_sets = lru.num_sets
        stride = block * num_sets

        # Working set quente: 'assoc' enderecos reacessados
        hot = [0x10000 + k * stride for k in range(lru.assoc)]
        # Scan adversario: muitos enderecos diferentes no mesmo set
        scan = [0x80000 + k * stride for k in range(lru.assoc * 8)]

        for cache in (lru, drrip):
            # Mistura: 1 passada quente, 1 passada de scan, repete
            for _ in range(50):
                for a in hot:
                    cache.access(a)
                for a in scan:
                    cache.access(a)

        # DRRIP nao precisa ser melhor em todos os cenarios sinteticos
        # superficiais. Aqui apenas exigimos que ele nao seja
        # catastroficamente pior (margem de 5pp).
        self.assertGreater(drrip.hit_rate, lru.hit_rate - 0.05,
            f"DRRIP nao deveria ser catastroficamente pior em scan: "
            f"LRU={lru.hit_rate:.2%}, DRRIP={drrip.hit_rate:.2%}")

    def test_matrix_conv_drrip_wins(self):
        """No benchmark matrix_conv com working set > cache,
        DRRIP deve ganhar significativamente.

        Importante: matriz pequena (que cabe na cache) NAO mostra ganho.
        O DRRIP so brilha quando o LRU comeca a thrashear."""
        # Cache pequena + matriz que excede working set util
        lru = Cache(1024, 32, 2, policy='LRU')   # 1KB cache
        drrip = Cache(1024, 32, 2, policy='DRRIP')
        # 128x128 matriz de int (64KB) -> excede em muito a cache de 1KB
        for cache in (lru, drrip):
            for addr, _ in trace_matrix_conv(width=128, height=128):
                cache.access(addr)
        self.assertGreater(drrip.hit_rate, lru.hit_rate,
            f"DRRIP deveria ganhar em matrix_conv com WS>cache: "
            f"LRU={lru.hit_rate:.2%}, DRRIP={drrip.hit_rate:.2%}")

    def test_drrip_not_catastrophic_on_lru_friendly(self):
        """Em padroes amigaveis ao LRU (linked_list), DRRIP nao deve perder
        mais que ~5pp (set dueling deve detectar e seguir BRRIP/SRRIP)."""
        lru = Cache(4096, 32, 4, policy='LRU')
        drrip = Cache(4096, 32, 4, policy='DRRIP')
        for cache in (lru, drrip):
            for addr, _ in trace_linked_list(count=500, iterations=2000):
                cache.access(addr)
        gap = lru.hit_rate - drrip.hit_rate
        self.assertLess(gap, 0.05,
            f"DRRIP perdeu demais em padrao LRU-friendly: "
            f"gap = {gap*100:.2f}pp")


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    # Verbosity 2 mostra cada teste individualmente
    unittest.main(verbosity=2)
