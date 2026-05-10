//============================================================================
// memory_hierarchy.v
// Hierarquia: L1I (instr) + L1D (dados) + L2 unificada.
// Parametro POLICY seleciona "DRRIP" (1) ou "LRU" (0) em todas as caches.
//
// Esta e' uma versao SIMPLIFICADA - nao trata coerencia ou writeback dirty.
// Para o trabalho final, expandir com:
//   - Politica de escrita (write-back vs write-through)
//   - Tratamento de conflito quando L1I e L1D pedem L2 simultaneamente
//   - Suporte a multi-palavra por bloco
//============================================================================

module memory_hierarchy #(
    parameter ADDR_W       = 32,
    parameter DATA_W       = 32,
    parameter L1_SIZE      = 4096,
    parameter L1_BLOCK     = 32,
    parameter L1_ASSOC     = 2,
    parameter L2_SIZE      = 32768,
    parameter L2_BLOCK     = 64,
    parameter L2_ASSOC     = 8,
    parameter POLICY       = 1     // 0 = LRU, 1 = DRRIP
)(
    input                    clk,
    input                    rst_n,

    // Instr fetch port (do core)
    input                    if_req_valid,
    input  [ADDR_W-1:0]      if_req_addr,
    output                   if_resp_valid,
    output [DATA_W-1:0]      if_resp_data,

    // Data port (do core)
    input                    dm_req_valid,
    input                    dm_req_we,
    input  [ADDR_W-1:0]      dm_req_addr,
    input  [DATA_W-1:0]      dm_req_wdata,
    output                   dm_resp_valid,
    output [DATA_W-1:0]      dm_resp_data,

    // Memoria principal (downstream da L2)
    output                   mm_req_valid,
    output                   mm_req_we,
    output [ADDR_W-1:0]      mm_req_addr,
    output [DATA_W-1:0]      mm_req_wdata,
    input                    mm_resp_valid,
    input  [DATA_W-1:0]      mm_resp_data
);

    //------------------------------------------------------------------------
    // Wires entre L1s e L2
    //------------------------------------------------------------------------
    wire l1i_to_l2_req_valid, l1i_to_l2_req_we;
    wire [ADDR_W-1:0] l1i_to_l2_req_addr;
    wire [DATA_W-1:0] l1i_to_l2_req_wdata;
    wire l2_to_l1i_resp_valid;
    wire [DATA_W-1:0] l2_to_l1i_resp_data;

    wire l1d_to_l2_req_valid, l1d_to_l2_req_we;
    wire [ADDR_W-1:0] l1d_to_l2_req_addr;
    wire [DATA_W-1:0] l1d_to_l2_req_wdata;
    wire l2_to_l1d_resp_valid;
    wire [DATA_W-1:0] l2_to_l1d_resp_data;

    //------------------------------------------------------------------------
    // Arbitro simples: prioridade L1D > L1I em conflito (politica comum
    // em cores in-order: dados sao mais criticos para forward progress).
    //------------------------------------------------------------------------
    wire arb_grant_d = l1d_to_l2_req_valid;
    wire arb_grant_i = l1i_to_l2_req_valid & ~arb_grant_d;

    wire l2_req_valid = arb_grant_d | arb_grant_i;
    wire l2_req_we    = arb_grant_d ? l1d_to_l2_req_we : 1'b0;
    wire [ADDR_W-1:0] l2_req_addr  = arb_grant_d ? l1d_to_l2_req_addr  : l1i_to_l2_req_addr;
    wire [DATA_W-1:0] l2_req_wdata = arb_grant_d ? l1d_to_l2_req_wdata : {DATA_W{1'b0}};

    wire l2_resp_valid;
    wire [DATA_W-1:0] l2_resp_data;

    // Roteamento da resposta da L2 baseado no requester (latch trivial).
    // ATENCAO: este e' simplificado; sintese real precisa de tag de quem
    // pediu para evitar race. Aqui assumimos transacoes serializadas.
    reg last_grant_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) last_grant_d <= 1'b0;
        else if (l2_req_valid) last_grant_d <= arb_grant_d;
    end
    assign l2_to_l1d_resp_valid = l2_resp_valid &  last_grant_d;
    assign l2_to_l1i_resp_valid = l2_resp_valid & ~last_grant_d;
    assign l2_to_l1d_resp_data  = l2_resp_data;
    assign l2_to_l1i_resp_data  = l2_resp_data;

    //------------------------------------------------------------------------
    // Instanciacao das caches (gera_DRRIP ou gera_LRU)
    //------------------------------------------------------------------------
    generate
        if (POLICY == 1) begin : gen_drrip
            cache_drrip #(
                .ADDR_W(ADDR_W), .DATA_W(DATA_W),
                .CACHE_SIZE(L1_SIZE), .BLOCK_SIZE(L1_BLOCK), .ASSOC(L1_ASSOC)
            ) u_l1i (
                .clk(clk), .rst_n(rst_n),
                .req_valid(if_req_valid), .req_we(1'b0),
                .req_addr(if_req_addr), .req_wdata({DATA_W{1'b0}}),
                .resp_valid(if_resp_valid), .resp_rdata(if_resp_data),
                .resp_hit(),
                .mem_req_valid(l1i_to_l2_req_valid),
                .mem_req_we(l1i_to_l2_req_we),
                .mem_req_addr(l1i_to_l2_req_addr),
                .mem_req_wdata(l1i_to_l2_req_wdata),
                .mem_resp_valid(l2_to_l1i_resp_valid),
                .mem_resp_data(l2_to_l1i_resp_data)
            );
            cache_drrip #(
                .ADDR_W(ADDR_W), .DATA_W(DATA_W),
                .CACHE_SIZE(L1_SIZE), .BLOCK_SIZE(L1_BLOCK), .ASSOC(L1_ASSOC)
            ) u_l1d (
                .clk(clk), .rst_n(rst_n),
                .req_valid(dm_req_valid), .req_we(dm_req_we),
                .req_addr(dm_req_addr), .req_wdata(dm_req_wdata),
                .resp_valid(dm_resp_valid), .resp_rdata(dm_resp_data),
                .resp_hit(),
                .mem_req_valid(l1d_to_l2_req_valid),
                .mem_req_we(l1d_to_l2_req_we),
                .mem_req_addr(l1d_to_l2_req_addr),
                .mem_req_wdata(l1d_to_l2_req_wdata),
                .mem_resp_valid(l2_to_l1d_resp_valid),
                .mem_resp_data(l2_to_l1d_resp_data)
            );
            cache_drrip #(
                .ADDR_W(ADDR_W), .DATA_W(DATA_W),
                .CACHE_SIZE(L2_SIZE), .BLOCK_SIZE(L2_BLOCK), .ASSOC(L2_ASSOC)
            ) u_l2 (
                .clk(clk), .rst_n(rst_n),
                .req_valid(l2_req_valid), .req_we(l2_req_we),
                .req_addr(l2_req_addr), .req_wdata(l2_req_wdata),
                .resp_valid(l2_resp_valid), .resp_rdata(l2_resp_data),
                .resp_hit(),
                .mem_req_valid(mm_req_valid),
                .mem_req_we(mm_req_we),
                .mem_req_addr(mm_req_addr),
                .mem_req_wdata(mm_req_wdata),
                .mem_resp_valid(mm_resp_valid),
                .mem_resp_data(mm_resp_data)
            );
        end else begin : gen_lru
            cache_lru #(
                .ADDR_W(ADDR_W), .DATA_W(DATA_W),
                .CACHE_SIZE(L1_SIZE), .BLOCK_SIZE(L1_BLOCK), .ASSOC(L1_ASSOC)
            ) u_l1i (
                .clk(clk), .rst_n(rst_n),
                .req_valid(if_req_valid), .req_we(1'b0),
                .req_addr(if_req_addr), .req_wdata({DATA_W{1'b0}}),
                .resp_valid(if_resp_valid), .resp_rdata(if_resp_data),
                .resp_hit(),
                .mem_req_valid(l1i_to_l2_req_valid),
                .mem_req_we(l1i_to_l2_req_we),
                .mem_req_addr(l1i_to_l2_req_addr),
                .mem_req_wdata(l1i_to_l2_req_wdata),
                .mem_resp_valid(l2_to_l1i_resp_valid),
                .mem_resp_data(l2_to_l1i_resp_data)
            );
            cache_lru #(
                .ADDR_W(ADDR_W), .DATA_W(DATA_W),
                .CACHE_SIZE(L1_SIZE), .BLOCK_SIZE(L1_BLOCK), .ASSOC(L1_ASSOC)
            ) u_l1d (
                .clk(clk), .rst_n(rst_n),
                .req_valid(dm_req_valid), .req_we(dm_req_we),
                .req_addr(dm_req_addr), .req_wdata(dm_req_wdata),
                .resp_valid(dm_resp_valid), .resp_rdata(dm_resp_data),
                .resp_hit(),
                .mem_req_valid(l1d_to_l2_req_valid),
                .mem_req_we(l1d_to_l2_req_we),
                .mem_req_addr(l1d_to_l2_req_addr),
                .mem_req_wdata(l1d_to_l2_req_wdata),
                .mem_resp_valid(l2_to_l1d_resp_valid),
                .mem_resp_data(l2_to_l1d_resp_data)
            );
            cache_lru #(
                .ADDR_W(ADDR_W), .DATA_W(DATA_W),
                .CACHE_SIZE(L2_SIZE), .BLOCK_SIZE(L2_BLOCK), .ASSOC(L2_ASSOC)
            ) u_l2 (
                .clk(clk), .rst_n(rst_n),
                .req_valid(l2_req_valid), .req_we(l2_req_we),
                .req_addr(l2_req_addr), .req_wdata(l2_req_wdata),
                .resp_valid(l2_resp_valid), .resp_rdata(l2_resp_data),
                .resp_hit(),
                .mem_req_valid(mm_req_valid),
                .mem_req_we(mm_req_we),
                .mem_req_addr(mm_req_addr),
                .mem_req_wdata(mm_req_wdata),
                .mem_resp_valid(mm_resp_valid),
                .mem_resp_data(mm_resp_data)
            );
        end
    endgenerate

endmodule
