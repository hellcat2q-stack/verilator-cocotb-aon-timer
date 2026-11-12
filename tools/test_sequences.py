"""Deterministic Cocotb translations of the AON Timer smoke, jump and prescaler scenarios."""

from __future__ import annotations

import json
import os
from functools import wraps
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from cocotb_coverage_adapter import CocotbCoverageAdapter


PUT_FULL_DATA = 0
GET = 4

WKUP_CTRL = 0x04
WKUP_THOLD_HI = 0x08
WKUP_THOLD_LO = 0x0C
WKUP_COUNT_HI = 0x10
WKUP_COUNT_LO = 0x14
WDOG_REGWEN = 0x18
WDOG_CTRL = 0x1C
WDOG_BARK_THOLD = 0x20
WDOG_BITE_THOLD = 0x24
WDOG_COUNT = 0x28
INTR_STATE = 0x2C
INTR_TEST = 0x30
WKUP_CAUSE = 0x34

DEFAULT_POOL_PATH = Path(__file__).resolve().parents[1] / "configs" / "stage05-test-pool.json"
_ACTIVE_COVERAGE: CocotbCoverageAdapter | None = None


def coverage_test(test_function):
    """Attach a bounded raw trace to one functional testcase."""
    @wraps(test_function)
    async def wrapped(dut):
        global _ACTIVE_COVERAGE
        recorder = CocotbCoverageAdapter(test_function.__name__)
        _ACTIVE_COVERAGE = recorder
        recorder.start_pin_monitor(dut)
        try:
            return await test_function(dut)
        finally:
            recorder.close()
            _ACTIVE_COVERAGE = None

    return cocotb.test()(wrapped)


def load_stimulus_pool() -> dict[str, dict]:
    pool_path = Path(os.environ.get("AON_TIMER_TEST_POOL", DEFAULT_POOL_PATH))
    with pool_path.open(encoding="utf-8") as stream:
        pool = json.load(stream)
    if pool.get("schema") != "aon-timer-stage05-test-pool-v1":
        raise ValueError(f"unsupported AON Timer test pool schema in {pool_path}")
    return {case["name"]: case["stimulus"] for case in pool["testcases"]}


STIMULUS_POOL = load_stimulus_pool()


async def transfer(dut, opcode: int, address: int, data: int = 0) -> int:
    await FallingEdge(dut.clk_i)
    dut.a_opcode_i.value = opcode
    dut.a_address_i.value = address
    dut.a_data_i.value = data
    dut.a_valid_i.value = 1

    for _ in range(200):
        await Timer(1, units="ns")
        if int(dut.a_ready_o.value):
            if opcode != GET and _ACTIVE_COVERAGE is not None:
                _ACTIVE_COVERAGE.on_write_address(address, data)
            break
        await FallingEdge(dut.clk_i)
    else:
        raise AssertionError(f"TL-UL request was not accepted at 0x{address:02x}")

    await FallingEdge(dut.clk_i)
    dut.a_valid_i.value = 0
    for _ in range(200):
        await Timer(1, units="ns")
        if int(dut.d_valid_o.value):
            assert int(dut.d_error_o.value) == 0, f"TL-UL error at 0x{address:02x}"
            response = int(dut.d_data_o.value)
            if opcode == GET and _ACTIVE_COVERAGE is not None:
                _ACTIVE_COVERAGE.on_read_data(address, response)
            elif opcode != GET and _ACTIVE_COVERAGE is not None:
                _ACTIVE_COVERAGE.on_write_data(address, data)
            await RisingEdge(dut.clk_i)
            return response
        await FallingEdge(dut.clk_i)
    raise AssertionError(f"TL-UL response timed out at 0x{address:02x}")


async def write_reg(dut, address: int, value: int) -> None:
    await transfer(dut, PUT_FULL_DATA, address, value & 0xFFFFFFFF)


async def read_reg(dut, address: int) -> int:
    return await transfer(dut, GET, address)


async def start_clocks_and_reset(dut) -> None:
    dut.clk_i.value = 0
    dut.clk_aon_i.value = 0
    dut.rst_ni.value = 0
    dut.rst_aon_ni.value = 0
    dut.a_valid_i.value = 0
    dut.a_opcode_i.value = 0
    dut.a_address_i.value = 0
    dut.a_data_i.value = 0

    cocotb.start_soon(Clock(dut.clk_aon_i, 100, units="ns").start())
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await Timer(220, units="ns")
    dut.rst_ni.value = 1
    dut.rst_aon_ni.value = 1
    await Timer(300, units="ns")


async def reset_again(dut) -> None:
    dut.rst_ni.value = 0
    dut.rst_aon_ni.value = 0
    dut.a_valid_i.value = 0
    await Timer(220, units="ns")
    dut.rst_ni.value = 1
    dut.rst_aon_ni.value = 1
    await Timer(300, units="ns")


async def initialize_disabled(dut) -> None:
    """Perform the common sequence's count clear and safe timer setup."""
    await write_reg(dut, WKUP_CTRL, 0)
    await write_reg(dut, WDOG_CTRL, 0)
    await write_reg(dut, INTR_STATE, 0b11)  # INTR_STATE is write-one-to-clear.
    await write_reg(dut, WKUP_CAUSE, 0)  # WKUP_CAUSE is write-zero-to-clear.
    await write_reg(dut, WKUP_COUNT_LO, 0)
    await write_reg(dut, WKUP_COUNT_HI, 0)
    await write_reg(dut, WDOG_COUNT, 0)
    await write_reg(dut, WKUP_THOLD_LO, 0)
    await write_reg(dut, WKUP_THOLD_HI, 0)
    await write_reg(dut, WDOG_BARK_THOLD, 0)
    await write_reg(dut, WDOG_BITE_THOLD, 0)


async def wait_for_high(dut, signal, label: str, max_aon_cycles: int = 100) -> int:
    if int(signal.value):
        return 0
    for cycle in range(1, max_aon_cycles + 1):
        await RisingEdge(dut.clk_aon_i)
        await Timer(1, units="ns")
        if int(signal.value):
            return cycle
    raise AssertionError(f"{label} did not assert within {max_aon_cycles} AON cycles")


@coverage_test
async def aon_timer_smoke_sequence(dut):
    """Translate the official smoke flow with fixed thresholds and explicit checks."""
    await start_clocks_and_reset(dut)
    await initialize_disabled(dut)

    stimulus = STIMULUS_POOL["aon_timer_smoke_sequence"]
    # The official sequence randomizes these in [1:10]; the frozen pool uses
    # explicit values so the initial corpus is deterministic and replayable.
    await write_reg(dut, WKUP_THOLD_LO, stimulus["wkup_threshold"])
    await write_reg(dut, WDOG_BARK_THOLD, stimulus["wdog_bark_threshold"])
    await write_reg(dut, WDOG_BITE_THOLD, stimulus["wdog_bite_threshold"])
    await write_reg(dut, WKUP_CTRL, 1)  # enable, prescaler=0
    await write_reg(dut, WDOG_CTRL, 1 | (stimulus["wdog_pause_in_sleep"] << 1))

    wkup_cycles = await wait_for_high(dut, dut.intr_wkup_o, "WKUP interrupt")
    bark_cycles = await wait_for_high(dut, dut.intr_wdog_o, "WDOG bark interrupt")
    bite_cycles = await wait_for_high(dut, dut.rst_req_o, "WDOG bite reset request")
    intr_state = await read_reg(dut, INTR_STATE)
    wkup_cause = await read_reg(dut, WKUP_CAUSE)

    assert intr_state & 0b11 == 0b11, f"expected both interrupt bits set, got 0x{intr_state:x}"
    assert wkup_cause & 1 == 1, f"expected WKUP_CAUSE.cause=1, got 0x{wkup_cause:x}"
    dut._log.info(
        "STAGE04_SMOKE_PASS wkup_cycles=%d bark_cycles=%d bite_cycles=%d intr_state=0x%x",
        wkup_cycles,
        bark_cycles,
        bite_cycles,
        intr_state,
    )


@coverage_test
async def aon_timer_jump_sequence(dut):
    """Check threshold changes while both counters run, including below-count updates."""
    await start_clocks_and_reset(dut)
    await initialize_disabled(dut)
    stimulus = STIMULUS_POOL["aon_timer_jump_sequence"]
    initial_count = stimulus["initial_count"]
    initial_threshold = stimulus["initial_threshold"]
    threshold_offset = stimulus["threshold_below_live_count_by"]
    await write_reg(dut, WKUP_COUNT_LO, initial_count)
    await write_reg(dut, WDOG_COUNT, initial_count)
    await write_reg(dut, WKUP_THOLD_LO, initial_threshold)
    await write_reg(dut, WDOG_BARK_THOLD, initial_threshold)
    await write_reg(dut, WDOG_BITE_THOLD, initial_threshold)
    await write_reg(dut, WKUP_CTRL, 1)
    await write_reg(dut, WDOG_CTRL, 1)

    # Let the counters advance, then lower each threshold below its live count.
    for _ in range(stimulus["counter_run_aon_cycles"]):
        await RisingEdge(dut.clk_aon_i)
        await Timer(1, units="ns")

    wkup_count = (await read_reg(dut, WKUP_COUNT_LO))
    wdog_count = await read_reg(dut, WDOG_COUNT)
    dut._log.info(
        "STAGE04_JUMP_OBSERVE wkup_ctrl=0x%x wkup_thold=0x%x wkup_count=%d "
        "wdog_ctrl=0x%x wdog_bark_thold=0x%x wdog_bite_thold=0x%x wdog_count=%d",
        await read_reg(dut, WKUP_CTRL),
        await read_reg(dut, WKUP_THOLD_LO),
        wkup_count,
        await read_reg(dut, WDOG_CTRL),
        await read_reg(dut, WDOG_BARK_THOLD),
        await read_reg(dut, WDOG_BITE_THOLD),
        wdog_count,
    )
    assert wkup_count > initial_count, f"WKUP_COUNT failed to advance from {initial_count}: {wkup_count}"
    assert wdog_count > initial_count, f"WDOG_COUNT failed to advance from {initial_count}: {wdog_count}"

    await write_reg(dut, WKUP_THOLD_LO, wkup_count - threshold_offset)
    await wait_for_high(dut, dut.intr_wkup_o, "WKUP interrupt after lowering threshold")
    await write_reg(dut, WDOG_BARK_THOLD, wdog_count - threshold_offset)
    await wait_for_high(dut, dut.intr_wdog_o, "WDOG bark after lowering threshold")
    assert int(dut.rst_req_o.value) == 0, "bite reset asserted before bite threshold was lowered"

    await write_reg(dut, WDOG_BITE_THOLD, wdog_count - threshold_offset)
    await wait_for_high(dut, dut.rst_req_o, "WDOG reset request after lowering bite threshold")
    dut._log.info(
        "STAGE04_JUMP_PASS initial_counts=%d wkup_count=%d wdog_count=%d",
        initial_count,
        wkup_count,
        wdog_count,
    )


@coverage_test
async def aon_timer_prescaler_sequence(dut):
    """Compare deterministic low/high prescaler settings and require slower counting."""
    await start_clocks_and_reset(dut)
    measured_cycles = {}

    stimulus = STIMULUS_POOL["aon_timer_prescaler_sequence"]
    for prescaler in stimulus["prescaler_values"]:
        await reset_again(dut)
        await initialize_disabled(dut)
        await write_reg(dut, WKUP_THOLD_LO, stimulus["wkup_threshold"])
        await write_reg(dut, WKUP_CTRL, prescaler << 1)
        await write_reg(dut, WKUP_CTRL, (prescaler << 1) | 1)
        measured_cycles[prescaler] = await wait_for_high(
            dut,
            dut.intr_wkup_o,
            f"WKUP interrupt at prescaler={prescaler}",
            max_aon_cycles=stimulus["max_expiry_aon_cycles"],
        )
        for _ in range(stimulus["count_readback_settle_aon_cycles"]):
            await RisingEdge(dut.clk_aon_i)
            await Timer(1, units="ns")
        count = await read_reg(dut, WKUP_COUNT_LO)
        dut._log.info(
            "STAGE04_PRESCALER_OBSERVE prescaler=%d ctrl=0x%x threshold=%d count=%d intr_state=0x%x",
            prescaler,
            await read_reg(dut, WKUP_CTRL),
            await read_reg(dut, WKUP_THOLD_LO),
            count,
            await read_reg(dut, INTR_STATE),
        )
        assert count >= 2, f"WKUP_COUNT below threshold at prescaler={prescaler}: {count}"

    assert measured_cycles[3] > measured_cycles[0], (
        "larger prescaler should require more AON clock cycles: "
        f"{measured_cycles}"
    )
    dut._log.info("STAGE04_PRESCALER_PASS cycles=%s", measured_cycles)


@coverage_test
async def aon_timer_intr_test_sequence(dut):
    """Translate the inherited CIP interrupt-test scenario for both AON IRQs."""
    await start_clocks_and_reset(dut)
    await initialize_disabled(dut)
    stimulus = STIMULUS_POOL["aon_timer_intr_test_sequence"]
    intr_test_mask = stimulus["intr_test_mask"]
    await write_reg(dut, INTR_TEST, intr_test_mask)

    for _ in range(stimulus["intr_propagation_aon_cycles"]):
        await RisingEdge(dut.clk_aon_i)
        await Timer(1, units="ns")

    intr_state = await read_reg(dut, INTR_STATE)
    assert intr_state & intr_test_mask == intr_test_mask, f"INTR_TEST did not set both state bits: 0x{intr_state:x}"
    assert int(dut.intr_wkup_o.value) == 1, "WKUP interrupt output did not assert"
    assert int(dut.intr_wdog_o.value) == 1, "WDOG interrupt output did not assert"

    await write_reg(dut, INTR_STATE, intr_test_mask)
    for _ in range(stimulus["intr_propagation_aon_cycles"]):
        await RisingEdge(dut.clk_aon_i)
        await Timer(1, units="ns")
    cleared = await read_reg(dut, INTR_STATE)
    assert cleared & 0b11 == 0, f"INTR_STATE W1C did not clear both bits: 0x{cleared:x}"
    assert int(dut.intr_wkup_o.value) == 0, "WKUP interrupt output stayed asserted after W1C"
    assert int(dut.intr_wdog_o.value) == 0, "WDOG interrupt output stayed asserted after W1C"
    dut._log.info("STAGE04_INTR_TEST_PASS state_before_clear=0x%x state_after_clear=0x%x", intr_state, cleared)
