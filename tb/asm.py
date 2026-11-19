"""Minimal RV32I assembler for the project-08 core.

Encodes the subset of RV32I the core implements. Used by the cocotb
testbench to assemble test programs into imem.hex.

API:
    asm = Assembler()
    asm.inst("addi", "x5", "x0", 10)
    asm.label("loop")
    asm.inst("beq", "x5", "x6", "@loop")   # label as immediate
    asm.write_hex("imem.hex")              # word-per-line hex, big-endian
"""


def reg(name):
    return int(name[1:]) if name.startswith("x") else int(name)


def sext(v, bits):
    v &= (1 << bits) - 1
    if v & (1 << (bits - 1)):
        v -= (1 << bits)
    return v


class Assembler:
    def __init__(self):
        self.items = []     # (addr, word) filled in pass 1
        self.labels = {}

    # ---- encoders (return 32-bit word) ----
    @staticmethod
    def _r(funct7, rs2, rs1, funct3, rd, opcode):
        return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

    @staticmethod
    def _i(imm, rs1, funct3, rd, opcode):
        imm &= 0xFFF
        return (imm << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

    @staticmethod
    def _s(imm, rs1, funct3, rs2, opcode):
        imm &= 0xFFF
        return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | ((imm & 0x1F) << 7) | opcode

    @staticmethod
    def _u(imm, rd, opcode):
        imm &= 0xFFFFF
        return (imm << 12) | (rd << 7) | opcode

    @staticmethod
    def _b(imm, rs1, funct3, rs2, opcode):
        imm &= 0x1FFF
        return ((imm >> 12) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15) \
             | (funct3 << 12) | (((imm >> 1) & 0xF) << 8) | ((imm & 1) << 7) | opcode

    @staticmethod
    def _j(imm, rd, opcode):
        imm &= 0x1FFFFF
        return ((imm >> 20) << 31) | (((imm >> 1) & 0x3FF) << 21) | (((imm >> 11) & 1) << 20) \
             | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | opcode

    OPC = {
        "lui": 0x37, "auipc": 0x17, "jal": 0x6F, "jalr": 0x67,
        "beq": 0x63, "bne": 0x63, "blt": 0x63, "bge": 0x63, "bltu": 0x63, "bgeu": 0x63,
        "lb": 0x03, "lh": 0x03, "lw": 0x03, "lbu": 0x03, "lhu": 0x03,
        "sb": 0x23, "sh": 0x23, "sw": 0x23,
        "addi": 0x13, "slti": 0x13, "sltiu": 0x13, "xori": 0x13, "ori": 0x13, "andi": 0x13,
        "slli": 0x13, "srli": 0x13, "srai": 0x13,
        "add": 0x33, "sub": 0x33, "sll": 0x33, "slt": 0x33, "sltu": 0x33,
        "xor": 0x33, "srl": 0x33, "sra": 0x33, "or": 0x33, "and": 0x33,
    }

    def inst(self, op, *args):
        self.items.append(("inst", op, args))

    def label(self, name):
        self.items.append(("label", name))

    def _addr_of(self, pc_target, pc_cur):
        return self.labels[pc_target] - pc_cur

    def _encode(self, op, args, pc_cur):
        rd, rs1, rs2, imm = None, None, None, None
        # parse args: registers are xN, immediates are ints or @label
        def is_reg(a):
            return isinstance(a, str) and a[0] == "x"

        if op == "ebreak":
            return 0x00100073
        if op in ("lui", "auipc"):
            rd, imm = reg(args[0]), self._imm(args[1], pc_cur)
            return self._u(imm, rd, self.OPC[op])
        if op == "jal":
            rd, imm = reg(args[0]), self._imm(args[1], pc_cur)
            return self._j(imm, rd, self.OPC[op])
        if op == "jalr":
            rd, rs1, imm = reg(args[0]), reg(args[1]), self._imm(args[2], pc_cur)
            return self._i(imm, rs1, 0, rd, self.OPC[op])
        if op in ("beq", "bne", "blt", "bge", "bltu", "bgeu"):
            rs1, rs2, imm = reg(args[0]), reg(args[1]), self._imm(args[2], pc_cur)
            f3 = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}[op]
            return self._b(imm, rs1, f3, rs2, self.OPC[op])
        if op in ("lb", "lh", "lw", "lbu", "lhu"):
            rd, rs1, imm = reg(args[0]), reg(args[1]), self._imm(args[2], pc_cur)
            f3 = {"lb": 0, "lh": 1, "lw": 2, "lbu": 4, "lhu": 5}[op]
            return self._i(imm, rs1, f3, rd, self.OPC[op])
        if op in ("sb", "sh", "sw"):
            rs2, rs1, imm = reg(args[0]), reg(args[1]), self._imm(args[2], pc_cur)
            f3 = {"sb": 0, "sh": 1, "sw": 2}[op]
            return self._s(imm, rs1, f3, rs2, self.OPC[op])
        if op in ("addi", "slti", "sltiu", "xori", "ori", "andi"):
            rd, rs1, imm = reg(args[0]), reg(args[1]), self._imm(args[2], pc_cur)
            f3 = {"addi": 0, "slti": 2, "sltiu": 3, "xori": 4, "ori": 6, "andi": 7}[op]
            return self._i(imm, rs1, f3, rd, self.OPC[op])
        if op in ("slli", "srli", "srai"):
            rd, rs1, shamt = reg(args[0]), reg(args[1]), self._imm(args[2], pc_cur)
            f3 = 1 if op == "slli" else 5
            f7 = 0 if op == "srai" else 0x20 if op == "srai" else 0
            if op == "srai":
                f7 = 0x20
            return self._i(shamt | (f7 << 5), rs1, f3, rd, self.OPC[op])
        if op in ("add", "sub", "sll", "slt", "sltu", "xor", "srl", "sra", "or", "and"):
            rd, rs1, rs2 = reg(args[0]), reg(args[1]), reg(args[2])
            f3 = {"add": 0, "sub": 0, "sll": 1, "slt": 2, "sltu": 3, "xor": 4, "srl": 5, "sra": 5, "or": 6, "and": 7}[op]
            f7 = {"sub": 0x20, "sra": 0x20}.get(op, 0)
            return self._r(f7, rs2, rs1, f3, rd, self.OPC[op])
        raise ValueError(f"unknown op {op}")

    def _imm(self, a, pc_cur):
        if isinstance(a, str) and a.startswith("@"):
            return sext(self.labels[a[1:]] - pc_cur, 12) if a[1:] in self.labels else 0
        if isinstance(a, str):
            return a if a.startswith("x") else int(a, 0)
        return a

    # ---- two-pass assembly ----
    def assemble(self):
        # pass 1: addresses
        addr = 0
        for item in self.items:
            if item[0] == "label":
                self.labels[item[1]] = addr
            else:
                addr += 4

        # pass 2: encode
        self.words = []
        addr = 0
        for item in self.items:
            if item[0] == "label":
                continue
            self.words.append(self._encode(item[1], item[2], addr))
            addr += 4
        return self.words

    def write_hex(self, path):
        self.assemble()
        with open(path, "w") as f:
            for w in self.words:
                f.write(f"{w:08x}\n")


def quick_program():
    """A program exercising the full RV32I subset. Returns (Assembler, expectations).
    Expectations: list of (reg_name, value) checked after halt."""
    a = Assembler()
    a.label("main")
    # immediate ops
    a.inst("addi", "x5", "x0", 10)        # x5 = 10
    a.inst("addi", "x6", "x0", 4)         # x6 = 4
    a.inst("add", "x7", "x5", "x6")       # x7 = 14
    a.inst("sub", "x8", "x5", "x6")       # x8 = 6
    a.inst("and", "x9", "x5", "x6")       # x9 = 10&4 = 0
    a.inst("or", "x10", "x5", "x6")       # x10 = 14
    a.inst("xor", "x11", "x5", "x6")      # x11 = 14
    a.inst("sll", "x12", "x5", "x6")      # x12 = 10<<4 = 160
    a.inst("srl", "x13", "x12", "x6")     # x13 = 160>>4 = 10
    a.inst("addi", "x14", "x0", -5)       # x14 = -5
    a.inst("sra", "x15", "x14", "x6")     # x15 = -5>>4 (arith) = -1 (0xFFFFFFFF)
    a.inst("slt", "x16", "x8", "x7")      # x16 = 6 < 14 = 1
    a.inst("sltu", "x17", "x14", "x6")    # x17 = (unsigned)0xFFFFFFFB < 4 = 0
    a.inst("slti", "x18", "x5", 7)        # x18 = 10 < 7 = 0
    a.inst("xori", "x19", "x5", 0xF)      # x19 = 10^15 = 5
    a.inst("ori", "x20", "x5", 0x4)       # x20 = 14
    a.inst("andi", "x21", "x5", 0xF)      # x21 = 10
    a.inst("slli", "x22", "x5", 3)        # x22 = 80
    a.inst("lui", "x23", 0x12345)         # x23 = 0x12345000
    a.inst("auipc", "x24", 0)             # x24 = pc (label-main-relative), value ~0
    a.inst("addi", "x25", "x0", 0x10)     # base for memory tests

    # stores / loads
    a.inst("sw", "x5", "x25", 0)          # mem[0x10] = 10
    a.inst("lw", "x26", "x25", 0)         # x26 = 10
    a.inst("sb", "x6", "x25", 4)          # mem[0x14] = 4 (byte)
    a.inst("lbu", "x27", "x25", 4)        # x27 = 4
    a.inst("sh", "x8", "x25", 8)          # mem[0x18] = 6 (half)
    a.inst("lhu", "x28", "x25", 8)        # x28 = 6

    # branches
    a.inst("addi", "x5", "x0", 7)         # x5 = 7
    a.inst("addi", "x6", "x0", 7)
    a.label("br_eq")
    a.inst("beq", "x5", "x6", "@br_taken")  # taken
    a.inst("addi", "x29", "x0", 0)          # not executed
    a.label("br_taken")
    a.inst("addi", "x29", "x0", 99)         # x29 = 99

    # jal / jalr: call a subroutine and return via x30
    a.label("call")
    a.inst("jal", "x30", "@subr")           # x30 = after_subr (return addr)
    a.label("after_subr")

    # bne/ blt / bge with correct signed/unsigned semantics:
    #   x5 = -3 (0xFFFFFFFD), x6 = 3
    a.inst("addi", "x5", "x0", -3)
    a.inst("addi", "x6", "x0", 3)
    a.inst("blt", "x5", "x6", "@t_signed_lt")   # -3 < 3 (signed) TRUE -> taken
    a.inst("addi", "x31", "x0", 0)
    a.label("t_signed_lt")
    a.inst("bge", "x6", "x5", "@t_signed_ge")   # 3 >= -3 (signed) TRUE -> taken
    a.inst("addi", "x31", "x0", 0)
    a.label("t_signed_ge")
    a.inst("bltu", "x6", "x5", "@t_uns_lt")     # 3 < 0xFFFFFFFD (unsigned) TRUE -> taken
    a.inst("addi", "x31", "x0", 0)
    a.label("t_uns_lt")
    a.inst("bgeu", "x6", "x5", "@bad")          # 3 >= 0xFFFFFFFD (unsigned) FALSE -> fall through
    a.inst("bne", "x5", "x6", "@t_ne")          # -3 != 3 TRUE -> taken
    a.inst("addi", "x31", "x0", 0)
    a.label("t_ne")
    a.inst("beq", "x6", "x5", "@bad")           # 3 == -3 FALSE -> fall through
    a.inst("addi", "x31", "x0", 1)              # x31 = 1
    a.inst("jal", "x0", "@done")                # skip over bad/subr

    a.label("bad")
    a.inst("addi", "x31", "x0", 0xDEAD)     # should not be reached

    # subroutine (jal target): sets x2, stores to dmem[0x40], returns via x30
    a.label("subr")
    a.inst("addi", "x2", "x0", 0x50)        # x2 = 0x50
    a.inst("sw", "x2", "x0", 0x40)          # dmem[0x40] = 0x50
    a.inst("jalr", "x0", "x30", 0)          # return

    a.label("done")
    a.inst("ebreak", "x0", "x0", 0)

    exp = {
        "x5": 0xFFFFFFFD, "x6": 3, "x7": 14, "x8": 6, "x9": 0, "x10": 14, "x11": 14,
        "x12": 160, "x13": 10, "x15": 0xFFFFFFFF, "x16": 1, "x17": 0,
        "x18": 0, "x19": 5, "x20": 14, "x21": 10, "x22": 80, "x23": 0x12345000,
        "x25": 0x10, "x26": 10, "x27": 4, "x28": 6,
        "x29": 99, "x30": None,  # x30 = return address, verify range
        "x31": 1,
    }
    return a, exp
