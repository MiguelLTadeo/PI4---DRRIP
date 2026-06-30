// ----------------------------------------------------------------------------
// tb_top.v — Wrappers que fixam parâmetros para cada configuração testada
//
// Cada wrapper é um módulo top-level distinto. Usamos `-s <top>` no
// iverilog ou seleção de top no ModelSim para escolher qual rodar.
// ----------------------------------------------------------------------------

module tb_cfgA_lru;
    tb_cache #(.SIZE_BYTES(4096),  .BLOCK_BYTES(32), .ASSOC(2), .POLICY(0),
               .CFG_NAME("A"), .BENCH_NAME("?")) u();
endmodule

module tb_cfgA_drrip;
    tb_cache #(.SIZE_BYTES(4096),  .BLOCK_BYTES(32), .ASSOC(2), .POLICY(1),
               .CFG_NAME("A"), .BENCH_NAME("?")) u();
endmodule

module tb_cfgB_lru;
    tb_cache #(.SIZE_BYTES(4096),  .BLOCK_BYTES(32), .ASSOC(4), .POLICY(0),
               .CFG_NAME("B"), .BENCH_NAME("?")) u();
endmodule

module tb_cfgB_drrip;
    tb_cache #(.SIZE_BYTES(4096),  .BLOCK_BYTES(32), .ASSOC(4), .POLICY(1),
               .CFG_NAME("B"), .BENCH_NAME("?")) u();
endmodule

module tb_cfgC_lru;
    tb_cache #(.SIZE_BYTES(8192),  .BLOCK_BYTES(32), .ASSOC(4), .POLICY(0),
               .CFG_NAME("C"), .BENCH_NAME("?")) u();
endmodule

module tb_cfgC_drrip;
    tb_cache #(.SIZE_BYTES(8192),  .BLOCK_BYTES(32), .ASSOC(4), .POLICY(1),
               .CFG_NAME("C"), .BENCH_NAME("?")) u();
endmodule
