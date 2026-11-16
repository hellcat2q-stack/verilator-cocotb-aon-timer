"""Instrument a verified isolated pinned export; preserve reference scoring logic."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from pathlib import Path

SCOREBOARD = "hw/ip/aon_timer/dv/env/aon_timer_scoreboard.sv"
SCOREBOARD_SHA = "b6534a47a116206144cdb332fcff9a58e49ef64eea965d9ddd8497f0b4d26d65"
SEQUENCE = "hw/ip/aon_timer/dv/env/seq_lib/aon_timer_smoke_vseq.sv"
TB = "hw/ip/aon_timer/dv/tb.sv"
TEST = "hw/ip/aon_timer/dv/tests/aon_timer_base_test.sv"
GROUP_FIELDS = {
    "timer_cfg_cg": ["prescale", "bark_thold", "bite_thold", "wkup_thold", "wdog_regwen", "pause_in_sleep", "wkup_cause"],
    "intr_cg": ["intr", "intr_en", "intr_state"],
    "intr_test_cg": ["intr", "intr_test", "intr_en", "intr_state"],
    "intr_pins_cg": ["intr_pin", "intr_pin_value"],
    "wake_up_timer_thold_hit_cg": ["wkup_int", "wkup_thold", "wkup_count"],
    "watchdog_timer_bark_thold_hit_cg": ["wdog_bark_int", "wdog_thold", "wdog_count"],
    "watchdog_timer_bite_thold_hit_cg": ["wdog_bite_rst", "wdog_thold", "wdog_count"],
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def display(fields: list[tuple[str, str, str]], kind: str) -> str:
    """Produce a single JSON marker; arguments are original pure expressions."""
    fmt = '{"kind":"' + kind + '",' + ",".join('"' + k + '":' + f for k, f, _ in fields) + "}"
    return '$display("AON_PARITY ' + fmt.replace('"', '\\"') + '", ' + ", ".join(a for _, _, a in fields) + ");"


def instrument_scoreboard(source: str) -> tuple[str, list[dict]]:
    # Balanced parentheses preserve named arguments in sample_pin(.idx(i)).
    patches = []
    sites = []
    for match in re.finditer(r"cov\.(\w+)\.sample\(", source):
        group = match.group(1)
        if group not in GROUP_FIELDS:
            raise ValueError(f"Unmapped sample site: {group}")
        depth, cursor, start = 1, match.end(), match.end()
        args = []
        while depth:
            char = source[cursor]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            if char == "," and depth == 1:
                args.append(source[start:cursor].strip())
                start = cursor + 1
            if depth == 0:
                args.append(source[start:cursor].strip())
            cursor += 1
        keys = GROUP_FIELDS[group]
        if len(keys) != len(args):
            raise ValueError(f"Wrong argument arity: {group}")
        fields = [("time_ps", "%0.0f", "$realtime / 1ps"),
                  ("seq", "%0d", "parity_sample_seq++"),
                  ("group", '"%0s"', '"' + group + '"')]
        fields += [(key, "%0d", arg) for key, arg in zip(keys, args)]
        indent = re.search(r"[^\n]*$", source[:match.start()]).group()
        patches.append((match.start(), display(fields, "sample") + "\n" + indent))
        sites.append({"group": group, "fields": keys, "original_arguments": args,
                      "original_line": source[:match.start()].count("\n") + 1})
    if len(sites) != 9:
        raise ValueError(f"Expected 9 sample sites, got {len(sites)}")
    for offset, insertion in reversed(patches):
        source = source[:offset] + insertion + source[offset:]
    source = source.replace("  // local variables", "  longint unsigned parity_sample_seq = 0;\n\n  // local variables", 1)
    anchor = "    // if access was to a valid csr, get the csr handle"
    tl = display([("time_ps", "%0.0f", "$realtime / 1ps"),
                  ("channel", "%0d", "channel"), ("write", "%0d", "write"),
                  ("address", "%0d", "csr_addr"), ("data", "%0d", "item.a_data"),
                  ("response", "%0d", "item.d_data")], "tl")
    source = source.replace(anchor, "    " + tl + "\n\n" + anchor, 1)
    return source, sites


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(exist_ok=False)
    originals = {name: (args.source_root / name).read_bytes() for name in (SCOREBOARD, SEQUENCE, TB, TEST)}
    if digest(originals[SCOREBOARD]) != SCOREBOARD_SHA:
        raise ValueError("Scoreboard is not the clean pinned reference")
    scoreboard, sites = instrument_scoreboard(originals[SCOREBOARD].decode())
    tb = originals[TB].decode()
    # Observers have no delays, drivers, backdoor calls, or reference-state assignments.
    extra = '''
  initial begin
    repeat (2) begin
      @(posedge clk);
      $display("AON_PARITY {\\"kind\\":\\"fast_edge\\",\\"time_ps\\":%0.0f}", $realtime / 1ps);
    end
  end
  always @(posedge clk_aon) begin
    $strobe("AON_PARITY {\\"kind\\":\\"edge\\",\\"time_ps\\":%0.0f,\\"rst_n\\":%0d,\\"rst_aon_n\\":%0d,\\"wkup_count\\":%0d,\\"wdog_count\\":%0d,\\"sleep\\":%0d,\\"wake_pin\\":%0d,\\"reset_pin\\":%0d}",
            $realtime / 1ps, rst_n, rst_aon_n, dut.u_core.wkup_count,
            dut.u_core.reg2hw_i.wdog_count.q, sleep, wkup_req, rst_req);
  end
  always @(rst_n or rst_aon_n) begin
    $display("AON_PARITY {\\"kind\\":\\"reset\\",\\"time_ps\\":%0.0f,\\"rst_n\\":%0b,\\"rst_aon_n\\":%0b}",
             $realtime / 1ps, rst_n, rst_aon_n);
  end
'''
    tb = tb.replace("\nendmodule", extra + "\nendmodule", 1)
    test = originals[TEST].decode().replace(
        "  // the base class dv_base_test creates the following instances:",
        """  // Freeze the diagnostic fast clock after base cfg randomization, before env build.
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    cfg.clk_freq_mhz = 50;
    foreach (cfg.clk_freqs_mhz[name]) cfg.clk_freqs_mhz[name] = 50;
  endfunction

  // the base class dv_base_test creates the following instances:""", 1)
    updated = {SCOREBOARD: scoreboard, TB: tb, TEST: test, SEQUENCE: Path(__file__).with_name("aon_timer_smoke_vseq.sv").read_text()}
    manifest = {"schema": "aon-timer-pinned-sample-instrumentation-v1", "files": [],
                "actual_sample_sites": sites, "reference_logic_fixes": [],
                "wakeup_low_word_double_read_preserved": True}
    patch = []
    for name, contents in updated.items():
        raw = contents.encode()
        manifest["files"].append({"path": name, "before_sha256": digest(originals[name]), "after_sha256": digest(raw)})
        patch.extend(difflib.unified_diff(originals[name].decode().splitlines(True), contents.splitlines(True), fromfile="a/" + name, tofile="b/" + name))
        (args.source_root / name).write_bytes(raw)
    (output / "instrumentation.patch").write_text("".join(patch))
    (output / "instrumentation.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
