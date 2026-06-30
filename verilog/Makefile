# Makefile — Projeto Integrador IV, Sprint 3
# Cache parametrizável (LRU/DRRIP) em Verilog, simulada com Icarus Verilog.
# Para usar o ModelSim, ver sim/run_modelsim.do.

RTL    := rtl/cache.v
TB     := tb/tb_cache.v tb/tb_top.v
SIMDIR := sim
TRDIR  := traces

CONFIGS  := A B C
POLICIES := lru drrip
BENCHES  := streaming_hotset matrix_conv linked_list pattern_search mixed_access

VVP_FILES := $(foreach c,$(CONFIGS),$(foreach p,$(POLICIES),$(SIMDIR)/cfg$(c)_$(p).vvp))

.PHONY: all clean traces run plot help

help:
	@echo "Targets disponiveis:"
	@echo "  make traces   - compila gerador de traces e gera os .hex"
	@echo "  make build    - compila todos os binarios Verilog (iverilog)"
	@echo "  make run      - roda todas as 30 simulacoes -> sim/results.csv"
	@echo "  make plot     - gera graficos (PNG) em docs/"
	@echo "  make all      - traces + build + run + plot"
	@echo "  make clean    - remove binarios e resultados"

traces: $(TRDIR)/gen_traces
	cd $(TRDIR) && ./gen_traces .

$(TRDIR)/gen_traces: $(TRDIR)/gen_traces.c
	gcc -O2 -Wall -o $@ $<

$(SIMDIR)/cfg%.vvp: $(RTL) $(TB)
	@mkdir -p $(SIMDIR)
	iverilog -g2001 -s tb_cfg$* -o $@ $(RTL) $(TB)

build: $(VVP_FILES)

run: build traces
	bash $(SIMDIR)/run_all.sh

plot: run
	python3 $(SIMDIR)/plot.py
	python3 $(SIMDIR)/plot_c_vs_verilog.py

all: plot

clean:
	rm -f $(VVP_FILES) $(SIMDIR)/results.csv
	rm -f $(TRDIR)/*.hex $(TRDIR)/gen_traces
	rm -f docs/*.png
