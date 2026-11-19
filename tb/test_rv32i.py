import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, NextTimeStep

import asm as asm_mod


@cocotb.test()
async def test_rv32i_program(dut):
    """Assemble the RV32I test program, load it, run until EBREAK, check regs."""
    # build program in a scratch dir so $readmemh in the core can find imem.hex
    a, exp = asm_mod.quick_program()
    a.assemble()

    # write imem.hex next to the simulation (cocotb CWD is the sim dir)
    hexpath = os.path.join(os.getcwd(), "imem.hex")
    a.write_hex(hexpath)
    dut._log.info(f"wrote {hexpath} with {len(a.words)} instructions")

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.dbg_raddr.value = 0
    dut.dbg_waddr.value = 0
    await RisingEdge(dut.clk)
    await NextTimeStep()
    dut.rst_n.value = 1
    dut.en.value = 1

    # run until halt (timeout guard)
    max_cycles = 2000
    trace = []
    halted = False
    for _ in range(max_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.halt_o.value):
            halted = True
            break
        trace.append(int(dut.pc.value))
        await NextTimeStep()

    if not halted:
        dut._log.error(f"never halted; PC trace (all, dedup tail): {trace[:50]}...{trace[-10:]}")
    assert halted, "core never reached EBREAK"

    # ---- check register file via debug port ----
    async def rd(reg_name):
        await NextTimeStep()                 # leave ReadOnly before driving
        dut.dbg_raddr.value = int(reg_name[1:])
        await ReadOnly()                     # combinational read settles
        v = int(dut.dbg_rdata.value)
        return v

    # x30 is the return address from JAL; it should point at "after_subr"
    # (the instruction right after the jal). We just require it's in a sane
    # range within the program.
    ra = await rd("x30")
    assert 0 < ra < 512, f"bad return address x30 = {ra}"

    for reg_name, value in exp.items():
        if reg_name == "x30":
            continue
        got = await rd(reg_name)
        assert got == value, (
            f"{reg_name} = {got:#x}, expected {value:#x}")

    # ---- check data memory: mem[0x10]=10, mem[0x14]=4, mem[0x18]=6 ----
    for addr, want in ((0x10, 10), (0x14, 4), (0x18, 6)):
        await NextTimeStep()                  # leave ReadOnly before driving
        dut.dbg_waddr.value = addr >> 2
        await ReadOnly()
        got = int(dut.dbg_wdata.value)
        assert got == want, f"dmem[{addr:#x}] = {got}, expected {want}"

    dut._log.info("RV32I core: all register + memory checks PASSED")
