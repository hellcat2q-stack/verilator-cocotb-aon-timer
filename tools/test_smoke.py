"""A minimal Cocotb smoke for the pinned AON Timer RTL and TL-UL path."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

PUT_FULL_DATA = 0
GET = 4
WKUP_THOLD_LO = 0x0C


async def transfer(dut, opcode, address, data=0):
    await FallingEdge(dut.clk_i)
    dut.a_opcode_i.value = opcode
    dut.a_address_i.value = address
    dut.a_data_i.value = data
    dut.a_valid_i.value = 1

    for _ in range(200):
        await Timer(1, units="ns")
        if int(dut.a_ready_o.value):
            break
        await FallingEdge(dut.clk_i)
    else:
        raise AssertionError("TL-UL request was not accepted")

    await FallingEdge(dut.clk_i)
    dut.a_valid_i.value = 0
    for _ in range(200):
        await Timer(1, units="ns")
        if int(dut.d_valid_o.value):
            assert int(dut.d_error_o.value) == 0, f"TL-UL error at 0x{address:02x}"
            response = int(dut.d_data_o.value)
            await RisingEdge(dut.clk_i)
            return response
        await FallingEdge(dut.clk_i)
    raise AssertionError("TL-UL response timed out")


@cocotb.test()
async def reset_dual_clock_and_register_read_write(dut):
    dut.clk_i.value = 0
    dut.clk_aon_i.value = 0
    dut.rst_ni.value = 0
    dut.rst_aon_ni.value = 0
    dut.a_valid_i.value = 0
    dut.a_opcode_i.value = 0
    dut.a_address_i.value = 0
    dut.a_data_i.value = 0

    cocotb.start_soon(Clock(dut.clk_aon_i, 100, units="ns").start())
    await Timer(1, units="ns")
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await Timer(220, units="ns")
    dut.rst_ni.value = 1
    dut.rst_aon_ni.value = 1
    await Timer(300, units="ns")

    initial = await transfer(dut, GET, WKUP_THOLD_LO)
    assert initial == 0, f"expected reset default 0, got 0x{initial:08x}"

    pattern = 0x12345678
    await transfer(dut, PUT_FULL_DATA, WKUP_THOLD_LO, pattern)
    actual = await transfer(dut, GET, WKUP_THOLD_LO)
    assert actual == pattern, f"register readback mismatch: 0x{actual:08x}"

    dut._log.info("STAGE02_SMOKE_PASS reset=checked dual_clock=checked tlul_write_read=checked")
