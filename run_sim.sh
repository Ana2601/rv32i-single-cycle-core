#!/bin/bash
# M1-native runner for the RV32I core: assemble + cocotb/Verilator check.
set -euo pipefail
cd "$(dirname "$0")"
# Optional venv ($HW_VENV, default /tmp/hw-portfolio-venv); otherwise any python with cocotb installed.
VENV="${HW_VENV:-/tmp/hw-portfolio-venv}"
export PATH="$VENV/bin:$PATH"
command -v cocotb-config >/dev/null || { echo "error: cocotb not found - run: pip install -r requirements.txt"; exit 1; }
export PYTHONPATH="$(pwd)"

TMP="$(mktemp -d /tmp/rv32i_sim.XXXXXX)"
cp src/rv32i_core.sv tb/asm.py tb/test_rv32i.py "$TMP/"

cat > "$TMP/Makefile" << 'EOF'
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
VERILOG_SOURCES = $(CURDIR)/rv32i_core.sv
TOPLEVEL = rv32i_core
MODULE = test_rv32i
PYTHONPATH = $(CURDIR)
EXTRA_ARGS += --timing -Wno-fatal -Wno-DECLFILENAME
include $(shell cocotb-config --makefiles)/Makefile.sim
EOF

(cd "$TMP" && make sim) > "$TMP/sim.log" 2>&1 \
    || { tail -40 "$TMP/sim.log"; exit 1; }

grep -E "RV32I|PASSED|FAILED|TESTS=" "$TMP/sim.log" | tail -6
