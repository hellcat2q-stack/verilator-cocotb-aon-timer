"""Replay the frozen VCS timeline with matrix-only reset and sleep support."""
from __future__ import annotations

import json
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

from pinned_sampling_matrix_adapter import PinnedSamplingMatrixAdapterV2


async def at_ps(target: int) -> None:
    delta = target - int(get_sim_time(units="ps"))
    if delta < 0:
        raise AssertionError(f"Missed replay timestamp by {-delta} ps")
    if delta:
        await Timer(delta, units="ps")


async def clock_at(signal, first: int, period: int) -> None:
    signal.value = 0
    await at_ps(first)
    await Clock(signal, period, units="ps").start()


@cocotb.test()
async def replay_uvm_accepted_stimulus(dut):
    source = json.loads(Path(os.environ["UVM_REPLAY_INPUT"]).read_text())
    assert source["run_status"] == "PASS", "Reference run failed; cannot claim a valid pair"
    records = source["records"]
    edges = [r for r in records if r["kind"] == "edge"]
    fast = [r for r in records if r["kind"] == "fast_edge"]
    assert len(fast) == 2 and fast[1]["time_ps"] - fast[0]["time_ps"] == 20000
    assert all(b["time_ps"] - a["time_ps"] == 5000000 for a, b in zip(edges, edges[1:]))
    begin = next(r["time_ps"] for r in records if r["kind"] == "begin")
    end = next(r["time_ps"] for r in records if r["kind"] == "end")
    transfers = [r for r in records if r["kind"] == "tl" and r["channel"] == 0]
    bus_records, edge_records = [], []
    dut.rst_ni.value = 0
    dut.rst_aon_ni.value = 0
    dut.a_valid_i.value = 0
    dut.a_opcode_i.value = 0
    dut.a_address_i.value = 0
    dut.a_data_i.value = 0
    dut.sleep_mode_i.value = 0
    adapter = PinnedSamplingMatrixAdapterV2("paired_case_" + str(source["case"]), seed=1)
    adapter.start_pin_monitor(dut)
    cocotb.start_soon(clock_at(dut.clk_i, fast[0]["time_ps"], 20000))
    cocotb.start_soon(clock_at(dut.clk_aon_i, edges[0]["time_ps"], 5000000))

    async def replay_time_inputs():
        reset_asserted = False
        for record in records:
            if record["kind"] not in {"reset", "sleep"}:
                continue
            await at_ps(record["time_ps"])
            if record["kind"] == "sleep":
                dut.sleep_mode_i.value = record["value"]
                continue
            for key, signal in (("rst_n", dut.rst_ni), ("rst_aon_n", dut.rst_aon_ni)):
                if record[key] in (0, 1):
                    signal.value = record[key]
            current_asserted = record["rst_n"] == 0 or record["rst_aon_n"] == 0
            if current_asserted and not reset_asserted:
                adapter.on_reset_asserted()
            reset_asserted = current_asserted

    async def monitor_edges():
        while True:
            await RisingEdge(dut.clk_aon_i)
            await ReadOnly()
            edge_records.append({"kind": "edge", "time_ps": int(get_sim_time(units="ps")),
                "rst_n": int(dut.rst_ni.value), "rst_aon_n": int(dut.rst_aon_ni.value),
                "wkup_count": int(dut.dbg_wkup_count_o.value), "wdog_count": int(dut.dbg_wdog_count_o.value),
                "sleep": int(dut.sleep_mode_i.value), "wake_pin": int(dut.wkup_req_o.value),
                "reset_pin": int(dut.rst_req_o.value)})

    reset_task = cocotb.start_soon(replay_time_inputs())
    edge_task = cocotb.start_soon(monitor_edges())
    try:
        for record in transfers:
            target = record["time_ps"]
            assert (target - fast[0]["time_ps"]) % 20000 == 0, "TL callback not on expected fast edge"
            await at_ps(target - 10000)
            dut.a_opcode_i.value = 0 if record["write"] else 4
            dut.a_address_i.value = record["address"]
            dut.a_data_i.value = record["data"]
            dut.a_valid_i.value = 1
            await at_ps(target)
            assert int(dut.a_ready_o.value), "RTL was not ready at reference acceptance time"
            bus_records.append({**record, "response": 0})
            offset = record["address"] & 0x3F
            if record["write"]:
                adapter.on_write_address(offset, record["data"])
            else:
                adapter.on_read_address(offset, record["data"])
            await Timer(10000, units="ps")
            dut.a_valid_i.value = 0
            for _ in range(200):
                await RisingEdge(dut.clk_i)
                if int(dut.d_valid_o.value):
                    assert not int(dut.d_error_o.value), "TL error"
                    response = int(dut.d_data_o.value)
                    bus_records.append({**record, "channel": 1,
                        "time_ps": int(get_sim_time(units="ps")), "response": response})
                    if record["write"]:
                        adapter.on_write_data(offset, record["data"])
                    else:
                        adapter.on_read_data(offset, response, record["data"])
                    break
            else:
                raise AssertionError("No TL response during replay")
        await at_ps(end + 100000)
    finally:
        edge_task.kill()
        reset_task.kill()
        trace_path = adapter.close()
        output = Path(os.environ["UVM_REPLAY_OUTPUT"])
        output.write_text(json.dumps({"schema": "aon-timer-cocotb-uvm-replay-v1",
            "case": source["case"], "seed": 1, "testcase": "replay_uvm_accepted_stimulus",
            "time_translation_ps": 0, "source_begin_time_ps": begin,
            "source_end_time_ps": end, "bus_records": bus_records,
            "edge_records": edge_records, "raw_adapter_trace_filename": trace_path.name,
            "coverage_vector": None, "coverage_credit_granted": 0}, indent=2) + "\n")
