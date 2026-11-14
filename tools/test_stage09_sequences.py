"""Real RTL actions for the engineering comparison, with readback checkpoints."""

import test_sequences as base


async def config_batch(dut, stimulus):
    await base.start_clocks_and_reset(dut)
    await base.initialize_disabled(dut)
    for step in stimulus["steps"]:
        wakeup = step["wkup_threshold"]
        await base.write_reg(dut, base.WKUP_THOLD_LO, wakeup & 0xFFFFFFFF)
        await base.write_reg(dut, base.WKUP_THOLD_HI, wakeup >> 32)
        await base.write_reg(dut, base.WDOG_BARK_THOLD, step["wdog_bark_threshold"])
        await base.write_reg(dut, base.WDOG_BITE_THOLD, step["wdog_bite_threshold"])
        await base.write_reg(dut, base.WKUP_CTRL, step["prescale"] << 1)
        await base.write_reg(dut, base.WDOG_CTRL, step["wdog_pause_in_sleep"] << 1)
        actual = {
            "wkup_thold": (await base.read_reg(dut, base.WKUP_THOLD_LO))
                          | (await base.read_reg(dut, base.WKUP_THOLD_HI)) << 32,
            "bark_thold": await base.read_reg(dut, base.WDOG_BARK_THOLD),
            "bite_thold": await base.read_reg(dut, base.WDOG_BITE_THOLD),
            "prescale": (await base.read_reg(dut, base.WKUP_CTRL)) >> 1,
            "pause_in_sleep": (await base.read_reg(dut, base.WDOG_CTRL)) >> 1,
        }
        expected = {"wkup_thold": wakeup, "bark_thold": step["wdog_bark_threshold"],
                    "bite_thold": step["wdog_bite_threshold"], "prescale": step["prescale"],
                    "pause_in_sleep": step["wdog_pause_in_sleep"]}
        assert actual == expected, f"RTL configuration readback mismatch: {actual} / {expected}"
        # timer_cfg samples at the write address phase before mirror updates.
        # This trailing W1C ensures all six programmed fields have been sampled.
        await base.write_reg(dut, base.INTR_STATE, 3)
        records = [sample for sample in base._ACTIVE_COVERAGE.trace.samples
                   if sample["covergroup"] == "timer_cfg_cg"]
        assert records, "missing configuration coverage"
        sample = records[-1]
        assert {key: sample["fields"][key] for key in actual} == actual, "trace mirror differs from RTL"
        sample["configuration_checkpoint"] = {"expected": expected, "rtl_readback": actual}
    dut._log.info("STAGE09_CONFIG_BATCH_PASS checkpoints=%d", len(stimulus["steps"]))


def register(action, stimulus):
    base_name = stimulus["base_test"]

    async def implementation(dut):
        if base_name == "aon_timer_config_batch_sequence":
            await config_batch(dut, stimulus)
        else:
            await getattr(base, base_name)(dut)

    implementation.__name__ = action
    implementation.__qualname__ = action
    return base.coverage_test(implementation)


for _name, _stimulus in base.STIMULUS_POOL.items():
    globals()[_name] = register(_name, _stimulus)
