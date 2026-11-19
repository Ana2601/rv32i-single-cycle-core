// Single-cycle RV32I core (base instruction set, no CSR/CSR instruction).
//
// Implements: LUI, AUIPC, JAL, JALR, BEQ/BNE/BLT/BGE/BLTU/BGEU, LB/LH/LW/LBU/LHU,
// SB/SH/SW, ADDI/SLTI/SLTIU/XORI/ORI/ANDI/SLLI/SRLI/SRAI, ADD/SUB/SLL/SLT/SLTU/
// XOR/SRL/SRA/OR/AND, EBREAK (halt).
//
// Verification hooks (synthesis-friendly debug ports):
//   dbg_raddr / dbg_rdata : read the register file
//   dbg_waddr / dbg_wdata : read a 32-bit word of the data memory
//   halt_o                : asserted when EBREAK executes
module rv32i_core (
    input  logic              clk,
    input  logic              rst_n,
    input  logic              en,          // run / stall
    output logic              halt_o,
    // register-file debug read
    input  logic [4:0]        dbg_raddr,
    output logic [31:0]       dbg_rdata,
    // data-memory debug word read
    input  logic [7:0]        dbg_waddr,
    output logic [31:0]       dbg_wdata
);
    // ---------------- memories ----------------
    logic [31:0] imem [0:127];     // 128 words = 512 B instruction memory
    logic [7:0]  dmem [0:1023];    // 1 KB data memory (byte-addressable)

    initial begin
        $readmemh("imem.hex", imem);
    end

    // ---------------- register file ----------------
    logic [31:0] regs [0:31];
    always_ff @(posedge clk) begin
        if (rst_n && en && wb_we && wb_rd != 5'd0)
            regs[wb_rd] <= wb_data;
    end

    // ---------------- fetch / decode ----------------
    logic [31:0] pc, pc_next;
    logic [31:0] instr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            pc <= 32'h0000_0000;
        else if (en)
            pc <= pc_next;
    end
    assign instr = imem[pc[8:2]];

    // instruction fields
    logic [4:0]  rd,  rs1, rs2;
    logic [2:0]  funct3;
    logic [6:0]  funct7, opcode;
    assign rd     = instr[11:7];
    assign funct3 = instr[14:12];
    assign rs1    = instr[19:15];
    assign rs2    = instr[24:20];
    assign funct7 = instr[31:25];
    assign opcode = instr[6:0];

    // immediate generation (I, S, B, U, J)
    logic [31:0] imm_i, imm_s, imm_b, imm_u, imm_j;
    assign imm_i = {{21{instr[31]}}, instr[30:20]};
    assign imm_s = {{21{instr[31]}}, instr[30:25], instr[11:7]};
    assign imm_b = {{20{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0};
    assign imm_u = {instr[31:12], 12'b0};
    assign imm_j = {{12{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0};

    // operand selection
    logic [31:0] alu_a, alu_b;
    assign alu_a = rs1_data;
    assign alu_b = (opcode == 7'b0110011) ? rs2_data : imm_i;

    // ---------------- ALU ----------------
    logic [3:0] alu_sel;
    logic [31:0] alu_out;
    logic alu_cmp;
    always_comb begin
        alu_out = 32'd0;
        case (alu_sel)
            4'd0:   alu_out = alu_a + alu_b;              // ADD
            4'd1:   alu_out = alu_a - alu_b;              // SUB
            4'd2:   alu_out = alu_a << alu_b[4:0];        // SLL
            4'd3:   alu_out = alu_a < alu_b ? 32'd1 : 32'd0;        // SLT
            4'd4:   alu_out = alu_a < alu_b ? 32'd1 : 32'd0;        // SLTU (unsigned)
            4'd5:   alu_out = alu_a ^ alu_b;              // XOR
            4'd6:   alu_out = alu_a >> alu_b[4:0];        // SRL
            4'd7:   alu_out = $signed(alu_a) >>> alu_b[4:0];        // SRA
            4'd8:   alu_out = alu_a | alu_b;              // OR
            4'd9:   alu_out = alu_a & alu_b;              // AND
            default: alu_out = 32'd0;
        endcase
    end
    // SLTU variant flag (uses unsigned compare)
    logic alu_sltu;
    assign alu_sltu = (alu_sel == 4'd4);

    // ---------------- control ----------------
    logic wb_we;
    logic [4:0] wb_rd;
    logic [31:0] wb_data;
    logic [31:0] rs1_data, rs2_data;
    logic [31:0] branch_target, jump_target;
    logic branch_taken;
    logic [31:0] pc_plus4;

    always_comb begin
        rs1_data = regs[rs1];
        rs2_data = regs[rs2];
    end
    assign pc_plus4     = pc + 32'd4;
    assign branch_target = pc + imm_b;
    assign jump_target   = pc + imm_j;

    // branch compare
    logic br_eq, br_ne, br_lt, br_ltu, br_ge, br_geu;
    assign br_eq = (rs1_data == rs2_data);
    assign br_ne = ~br_eq;
    assign br_lt = $signed(rs1_data) < $signed(rs2_data);
    assign br_ltu= rs1_data < rs2_data;
    assign br_ge = ~br_lt;
    assign br_geu= ~br_ltu;

    always_comb begin
        branch_taken = 1'b0;
        case (opcode)
            7'b1100011: begin
                case (funct3)
                    3'd0:   branch_taken = br_eq;
                    3'd1:   branch_taken = br_ne;
                    3'd4:   branch_taken = br_lt;
                    3'd5:   branch_taken = br_ge;
                    3'd6:   branch_taken = br_ltu;
                    3'd7:   branch_taken = br_geu;
                    default: branch_taken = 1'b0;
                endcase
            end
            default: branch_taken = 1'b0;
        endcase
    end

    // ALU selection & register writeback by opcode/funct
    logic is_load, is_store, is_branch, is_jal, is_jalr, is_lui, is_auipc,
          is_op, is_opimm, is_ebreak;
    assign is_lui    = (opcode == 7'b0110111);
    assign is_auipc  = (opcode == 7'b0010111);
    assign is_jal    = (opcode == 7'b1101111);
    assign is_jalr   = (opcode == 7'b1100111);
    assign is_branch = (opcode == 7'b1100011);
    assign is_load   = (opcode == 7'b0000011);
    assign is_store  = (opcode == 7'b0100011);
    assign is_opimm  = (opcode == 7'b0010011);
    assign is_op     = (opcode == 7'b0110011);
    assign is_ebreak = (opcode == 7'b1110011) && (instr[31:20] == 12'h001);

    always_comb begin
        alu_sel = 4'd0;
        case (opcode)
            7'b0010011: begin   // OP-IMM
                case (funct3)
                    3'd0:   alu_sel = 4'd0;   // ADDI
                    3'd2:   alu_sel = 4'd3;   // SLTI
                    3'd3:   alu_sel = 4'd4;   // SLTIU
                    3'd4:   alu_sel = 4'd5;   // XORI
                    3'd6:   alu_sel = 4'd8;   // ORI
                    3'd7:   alu_sel = 4'd9;   // ANDI
                    3'd1:   alu_sel = (instr[30]) ? 4'd7 : 4'd2; // SRAI / SLLI
                    3'd5:   alu_sel = (instr[30]) ? 4'd7 : 4'd6; // SRAI / SRLI
                    default: alu_sel = 4'd0;
                endcase
            end
            7'b0110011: begin   // OP
                case (funct3)
                    3'd0:   alu_sel = (funct7[5]) ? 4'd1 : 4'd0; // SUB / ADD
                    3'd1:   alu_sel = 4'd2;                       // SLL
                    3'd2:   alu_sel = 4'd3;                       // SLT
                    3'd3:   alu_sel = 4'd4;                       // SLTU
                    3'd4:   alu_sel = 4'd5;                       // XOR
                    3'd5:   alu_sel = (funct7[5]) ? 4'd7 : 4'd6;  // SRA / SRL
                    3'd6:   alu_sel = 4'd8;                       // OR
                    3'd7:   alu_sel = 4'd9;                       // AND
                    default: alu_sel = 4'd0;
                endcase
            end
            default: alu_sel = 4'd0;
        endcase
    end

    // writeback data
    logic [31:0] mem_rd_data;
    always_comb begin
        wb_data = 32'd0;
        if (is_lui)
            wb_data = imm_u;
        else if (is_auipc)
            wb_data = pc + imm_u;
        else if (is_jal || is_jalr)
            wb_data = pc_plus4;
        else if (is_load)
            wb_data = mem_rd_data;
        else if (is_op || is_opimm)
            wb_data = alu_out;
    end

    // write-enable (not stores/branches, and not x0 target for jumps)
    assign wb_we  = ~(is_store | is_branch | is_ebreak);
    assign wb_rd  = rd;

    // ---------------- data memory access ----------------
    logic [31:0] mem_addr;
    assign mem_addr = (is_load || is_store) ? (rs1_data + (is_store ? imm_s : imm_i)) : 32'd0;

    logic [31:0] dmem_word;
    assign dmem_word = {dmem[mem_addr[9:0]+3], dmem[mem_addr[9:0]+2],
                        dmem[mem_addr[9:0]+1], dmem[mem_addr[9:0]+0]};

    always_comb begin
        mem_rd_data = 32'd0;
        case (funct3)
            3'd0:   mem_rd_data = {{24{dmem_word[7]}}, dmem_word[7:0]};   // LB
            3'd1:   mem_rd_data = {{16{dmem_word[15]}}, dmem_word[15:0]}; // LH
            3'd2:   mem_rd_data = dmem_word;                              // LW
            3'd4:   mem_rd_data = {24'd0, dmem_word[7:0]};                // LBU
            3'd5:   mem_rd_data = {16'd0, dmem_word[15:0]};               // LHU
            default: mem_rd_data = dmem_word;
        endcase
    end

    // ---------------- stores ----------------
    always_ff @(posedge clk) begin
        if (rst_n && en && is_store) begin
            case (funct3)
                3'd0:   dmem[mem_addr[9:0]+0] <= rs2_data[7:0];   // SB
                3'd1:   begin
                            dmem[mem_addr[9:0]+0] <= rs2_data[7:0];
                            dmem[mem_addr[9:0]+1] <= rs2_data[15:8];
                        end
                3'd2:   begin
                            dmem[mem_addr[9:0]+0] <= rs2_data[7:0];
                            dmem[mem_addr[9:0]+1] <= rs2_data[15:8];
                            dmem[mem_addr[9:0]+2] <= rs2_data[23:16];
                            dmem[mem_addr[9:0]+3] <= rs2_data[31:24];
                        end
                default: ;
            endcase
        end
    end

    // ---------------- PC next ----------------
    always_comb begin
        pc_next = pc_plus4;
        if (is_jal)
            pc_next = jump_target;
        else if (is_jalr)
            pc_next = (rs1_data + imm_i) & 32'hFFFF_FFFE;
        else if (is_branch && branch_taken)
            pc_next = branch_target;
    end

    // ---------------- halt ----------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            halt_o <= 1'b0;
        else if (en && is_ebreak)
            halt_o <= 1'b1;
    end

    // ---------------- debug reads ----------------
    assign dbg_rdata = regs[dbg_raddr];
    assign dbg_wdata = {dmem[dbg_waddr*4+3], dmem[dbg_waddr*4+2],
                        dmem[dbg_waddr*4+1], dmem[dbg_waddr*4+0]};
endmodule
