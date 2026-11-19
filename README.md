# RISC-V core (RV32I) in SystemVerilog

[![CI](https://github.com/Ana2601/rv32i-single-cycle-core/actions/workflows/ci.yml/badge.svg)](https://github.com/Ana2601/rv32i-single-cycle-core/actions/workflows/ci.yml)

A from-scratch single-cycle RV32I core with a hand-written assembler and a
program-level verification testbench. Runs entirely on M1.

## Core

`src/rv32i_core.sv` implements the full RV32I base integer instruction set
(no CSR/privileged instructions):

- **U-type**: LUI, AUIPC
- **J-type**: JAL, JALR (with `& ~1` link-address alignment)
- **B-type**: BEQ, BNE, BLT, BGE, BLTU, BGEU (signed and unsigned)
- **loads**: LB, LH, LW, LBU, LHU (sign/zero-extension)
- **stores**: SB, SH, SW
- **OP-IMM**: ADDI, SLTI, SLTIU, XORI, ORI, ANDI, SLLI, SRLI, SRAI
- **OP**: ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND
- **SYSTEM**: EBREAK (asserts `halt_o`)

Design features:
- single-cycle datapath: fetch -> decode -> ALU -> writeback in one clock
- 128-word instruction memory (loaded via `$readmemh("imem.hex")`)
- 1 KB byte-addressable data memory with correct sub-word access
- synthesis-friendly debug ports: `dbg_raddr/rdata` read the register file,
  `dbg_waddr/wdata` read a word of data memory, `halt_o` flags EBREAK

## Assembler

`tb/asm.py` is a small two-pass RV32I assembler (~150 lines) with label
support: `addi x5, x0, -3`, `beq x5, x6, @label`, etc. It produces the
`imem.hex` the core loads. This keeps the whole flow self-contained (no
toolchain download needed).

## Test

`tb/test_rv32i.py` assembles a 52-instruction program that:

1. exercises every ALU op and its immediate variant,
2. verifies the pipeline via a `lui`/`auipc` pair,
3. tests loads/stores incl. byte and half-word (sign handling),
4. takes every branch variant (signed/unsigned, taken and not-taken),
5. calls a subroutine with `jal` and returns with `jalr`,
6. then asserts the register file (via the debug port) and the data memory.

```
** TESTS=1 PASS=1 FAIL=0 SKIP=0
RV32I core: all register + memory checks PASSED
```

## Layout

```
src/rv32i_core.sv      the core
tb/asm.py              two-pass RV32I assembler
tb/test_rv32i.py       program-level verification (cocotb + Verilator)
run_sim.sh             one-command flow
Makefile               convenience targets
```

## Run

```bash
./run_sim.sh            # assemble + compile + verify
make sim                # same
```


## Next (FPGA host)

- Run the core through the **RISCOF** compliance suite (rv32i/priv tests) via
  Spike co-sim to close the formal-compliance gap.
- Swap in a richer open core (Ibex / VexRiscv) and take to build for a
  soft-SoC on the FPGA host.

## Setup

- [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) (Icarus Verilog, Verilator, Yosys)
- Python packages: `pip install -r requirements.txt`

```bash
./run_sim.sh
```

The same commands run in CI on every push (`.github/workflows/ci.yml`).
