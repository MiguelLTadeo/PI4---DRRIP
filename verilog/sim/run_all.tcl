# run_all.tcl — Roda as 30 combinacoes (3 configs x 5 benchmarks x 2 politicas)
# em batch no ModelSim. Imprime hit_rate de cada uma.
#
# Uso: a partir da pasta raiz do projeto (sprint3/):
#   ModelSim> do sim/run_all.tcl
#
# Voce pode redirecionar a saida com:
#   ModelSim> transcript file sim/results_modelsim.txt
#   ModelSim> do sim/run_all.tcl
#   ModelSim> transcript file ""

# --- Setup: limpa work, recompila uma vez --------------------------------
if {[file isdirectory work]} { vdel -all -lib work }
vlib work
vmap work work

vlog rtl/cache.v
vlog tb/tb_cache.v
vlog tb/tb_top.v

# --- Loops -------------------------------------------------------------
set CONFIGS  {A B C}
set BENCHES  {streaming_hotset matrix_conv linked_list pattern_search mixed_access}
set POLICIES {lru drrip}

echo "==== Rodando 30 simulacoes ===="

foreach cfg $CONFIGS {
    foreach bench $BENCHES {
        foreach pol $POLICIES {
            set top "tb_cfg${cfg}_${pol}"
            set trace "traces/${bench}.hex"
            echo "----"
            echo "Config $cfg | $bench | $pol"
            vsim -c +TRACE=$trace work.$top
            run -all
        }
    }
}

echo "==== Fim. Procure 'RESULT' no transcript. ===="
