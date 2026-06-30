// ============================================================================
// cache_drrip.v — Cache set-associativa com politica DRRIP (Jaleel et al.)
//
// Projeto Integrador IV — Sprint 3
// UNIPAMPA — Engenharia de Computacao
//
// DRRIP canonico (ISCA 2010):
//   - RRPV de 2 bits por linha (0=imediato, 3=distante)
//   - Hit Priority: hit -> RRPV=0
//   - SRRIP insere em RRPV=2
//   - BRRIP insere em RRPV=3 (1/32 das vezes em RRPV=2 — bimodal)
//   - Set dueling: 1/16 dos sets sao leaders SRRIP, 1/16 sao leaders BRRIP,
//     resto sao followers que consultam o PSEL (contador 10 bits)
//   - Vitima: linha com RRPV=3; senao, envelhece todas e tenta de novo
// ============================================================================

`timescale 1ns / 1ps

module cache #(
    parameter integer SIZE_BYTES  = 4096,    // tamanho total da cache
    parameter integer BLOCK_BYTES = 32,      // tamanho do bloco
    parameter integer ASSOC       = 2,       // associatividade
    parameter integer ADDR_W      = 32       // largura do endereco
) (
    input  wire              clk,
    input  wire              rst_n,

    // Interface de acesso (1 acesso por ciclo)
    input  wire              req_valid,
    input  wire [ADDR_W-1:0] req_addr,

    // Resposta (mesmo ciclo)
    output reg               resp_hit,
    output reg               resp_valid,

    // Contadores
    output reg  [31:0]       cnt_hits,
    output reg  [31:0]       cnt_misses,
    output reg  [31:0]       cnt_accesses
);

// ----------------------------------------------------------------------------
// Parametros derivados
// ----------------------------------------------------------------------------
localparam integer NUM_SETS    = SIZE_BYTES / (BLOCK_BYTES * ASSOC);
localparam integer OFFSET_BITS = $clog2(BLOCK_BYTES);
localparam integer INDEX_BITS  = $clog2(NUM_SETS);
localparam integer TAG_BITS    = ADDR_W - OFFSET_BITS - INDEX_BITS;
localparam integer WAY_BITS    = $clog2(ASSOC);
localparam integer MAX_RRPV    = 3;

localparam integer PSEL_BITS   = 10;
localparam integer PSEL_MAX    = (1 << PSEL_BITS) - 1;
localparam integer PSEL_MID    = (1 << (PSEL_BITS-1));
localparam integer BIP_MAX     = 32;

localparam integer NUM_LEADERS = (NUM_SETS/16 <  4) ?  4 :
                                 (NUM_SETS/16 > 32) ? 32 :
                                 (NUM_SETS/16);

// ----------------------------------------------------------------------------
// Memorias internas
// ----------------------------------------------------------------------------
reg                  valid_arr [0:NUM_SETS-1][0:ASSOC-1];
reg [TAG_BITS-1:0]   tag_arr   [0:NUM_SETS-1][0:ASSOC-1];
reg [1:0]            rrpv_arr  [0:NUM_SETS-1][0:ASSOC-1];

reg [PSEL_BITS-1:0]  psel;
reg [4:0]            bip_counter;

// ----------------------------------------------------------------------------
// Decomposicao do endereco
// ----------------------------------------------------------------------------
wire [INDEX_BITS-1:0] set_idx = req_addr[OFFSET_BITS +: INDEX_BITS];
wire [TAG_BITS-1:0]   tag_in  = req_addr[ADDR_W-1 -: TAG_BITS];

// ----------------------------------------------------------------------------
// Lookup combinacional
// ----------------------------------------------------------------------------
reg              hit_c;
reg [WAY_BITS:0] hit_way_c;
integer w;

always @* begin
    hit_c     = 1'b0;
    hit_way_c = ASSOC[WAY_BITS:0];
    for (w = 0; w < ASSOC; w = w + 1) begin
        if (valid_arr[set_idx][w] && (tag_arr[set_idx][w] == tag_in)) begin
            hit_c     = 1'b1;
            hit_way_c = w[WAY_BITS:0];
        end
    end
end

// Busca via invalida (cold start)
reg              has_invalid_c;
reg [WAY_BITS:0] invalid_way_c;
integer iw;

always @* begin
    has_invalid_c = 1'b0;
    invalid_way_c = ASSOC[WAY_BITS:0];
    for (iw = 0; iw < ASSOC; iw = iw + 1) begin
        if (!valid_arr[set_idx][iw] && !has_invalid_c) begin
            has_invalid_c = 1'b1;
            invalid_way_c = iw[WAY_BITS:0];
        end
    end
end

// Busca via com RRPV=MAX; tambem calcula o gap para aging
reg              has_max_c;
reg [WAY_BITS-1:0] victim_c;
reg [1:0]          cur_max_c;
integer dw;

always @* begin
    has_max_c = 1'b0;
    victim_c  = 0;
    cur_max_c = 0;
    for (dw = 0; dw < ASSOC; dw = dw + 1) begin
        if (rrpv_arr[set_idx][dw] > cur_max_c)
            cur_max_c = rrpv_arr[set_idx][dw];
        if (rrpv_arr[set_idx][dw] == MAX_RRPV[1:0] && !has_max_c) begin
            has_max_c = 1'b1;
            victim_c  = dw[WAY_BITS-1:0];
        end
    end
end

wire [1:0] gap_c = MAX_RRPV[1:0] - cur_max_c;

// ----------------------------------------------------------------------------
// Set dueling
// ----------------------------------------------------------------------------
wire [INDEX_BITS:0] set_idx_ext = {1'b0, set_idx};
wire is_srrip_leader = (set_idx_ext < NUM_LEADERS);
wire is_brrip_leader = (set_idx_ext >= NUM_LEADERS) &&
                       (set_idx_ext <  (2*NUM_LEADERS));

wire use_brrip = is_brrip_leader ? 1'b1 :
                 is_srrip_leader ? 1'b0 :
                 (psel >= PSEL_MID[PSEL_BITS-1:0]);

wire brrip_insert_close = (bip_counter == (BIP_MAX-1));

wire [WAY_BITS-1:0] final_victim = has_invalid_c ? invalid_way_c[WAY_BITS-1:0]
                                                 : victim_c;

// ----------------------------------------------------------------------------
// Logica sequencial
// ----------------------------------------------------------------------------
integer s, ww;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        for (s = 0; s < NUM_SETS; s = s + 1) begin
            for (ww = 0; ww < ASSOC; ww = ww + 1) begin
                valid_arr[s][ww] <= 1'b0;
                tag_arr  [s][ww] <= {TAG_BITS{1'b0}};
                rrpv_arr [s][ww] <= MAX_RRPV[1:0];
            end
        end
        psel         <= PSEL_MID[PSEL_BITS-1:0];
        bip_counter  <= 5'd0;
        cnt_hits     <= 32'd0;
        cnt_misses   <= 32'd0;
        cnt_accesses <= 32'd0;
        resp_hit     <= 1'b0;
        resp_valid   <= 1'b0;
    end
    else begin
        resp_valid <= req_valid;
        resp_hit   <= 1'b0;

        if (req_valid) begin
            cnt_accesses <= cnt_accesses + 1;

            if (hit_c) begin
                // HIT: Hit Priority -> RRPV = 0
                cnt_hits <= cnt_hits + 1;
                resp_hit <= 1'b1;
                rrpv_arr[set_idx][hit_way_c[WAY_BITS-1:0]] <= 2'b00;
            end
            else begin
                // MISS
                cnt_misses <= cnt_misses + 1;

                // Instala
                valid_arr[set_idx][final_victim] <= 1'b1;
                tag_arr  [set_idx][final_victim] <= tag_in;

                // Aging: se ninguem em MAX_RRPV, soma o gap a todos
                if (!has_max_c && !has_invalid_c) begin
                    for (ww = 0; ww < ASSOC; ww = ww + 1)
                        rrpv_arr[set_idx][ww] <= rrpv_arr[set_idx][ww] + gap_c;
                end

                // Insercao segundo a politica
                if (use_brrip) begin
                    // BRRIP bimodal
                    rrpv_arr[set_idx][final_victim] <=
                        brrip_insert_close ? 2'd2 : MAX_RRPV[1:0];
                    bip_counter <= brrip_insert_close ? 5'd0
                                                     : (bip_counter + 1);
                end
                else begin
                    // SRRIP
                    rrpv_arr[set_idx][final_victim] <= 2'd2;
                end

                // PSEL: miss em leader penaliza a politica do leader
                if (is_srrip_leader && psel < PSEL_MAX[PSEL_BITS-1:0])
                    psel <= psel + 1;
                else if (is_brrip_leader && psel > 0)
                    psel <= psel - 1;
            end
        end
    end
end

endmodule
