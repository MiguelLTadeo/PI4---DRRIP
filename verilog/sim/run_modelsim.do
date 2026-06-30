# run_modelsim.do — Script ModelSim equivalente ao fluxo Makefile
#
# Uso no ModelSim (na linha de comando ou do menu Tools->TCL):
#   cd <caminho do projeto>
#   do sim/run_modelsim.do
#
# O script compila o RTL, todos os top-levels da testbench, e roda uma
# simulação de exemplo (Config A, LRU, streaming_hotset). Para rodar
# outras combinações, substitua o comando `vsim` no final.

# --- Setup -------------------------------------------------------------
if {[file isdirectory work]} { vdel -all -lib work }
vlib work
vmap work work

# --- Compilação --------------------------------------------------------
# Verilog-2001 puro; nao precisa de -sv2k12 nem outras flags especiais
vlog rtl/cache.v
vlog tb/tb_cache.v
vlog tb/tb_top.v

# --- Simulação (exemplo: Config A LRU em streaming_hotset) --------------
# Para mudar de configuração/política, troque o top-level abaixo:
#   tb_cfgA_lru | tb_cfgA_drrip
#   tb_cfgB_lru | tb_cfgB_drrip
#   tb_cfgC_lru | tb_cfgC_drrip
vsim -c +TRACE=traces/streaming_hotset.hex work.tb_cfgA_lru
run -all

