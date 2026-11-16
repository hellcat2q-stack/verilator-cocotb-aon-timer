// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
// Declared diagnostic replacement in an isolated pinned tree only.
class aon_timer_smoke_vseq extends aon_timer_base_vseq;
  `uvm_object_utils(aon_timer_smoke_vseq)
  `uvm_object_new

  constraint parity_initial_c {
    initial_lc_escalate_en == 0;
    initial_sleep_mode == 0;
    wdog_regwen == 1;
  }

  task parity_write(uvm_reg reg_handle, uvm_reg_data_t value);
    @(negedge cfg.aon_clk_rst_vif.clk);
    cfg.clk_rst_vif.wait_clks(5);
    csr_utils_pkg::csr_wr(reg_handle, value);
  endtask

  virtual task body();
    int parity_case = 0;
    uvm_reg_data_t intr_value;
    void'($value$plusargs("aon_parity_case=%d", parity_case));
    `DV_CHECK_FATAL(parity_case inside {[0:2]})
    cfg.lc_escalate_en_vif.drive(0);
    cfg.sleep_vif.drive(0);
    $display("AON_PARITY {\"kind\":\"begin\",\"time_ps\":%0.0f,\"case\":%0d}",
             $realtime / 1ps, parity_case);
    parity_write(ral.wkup_ctrl, 0);
    parity_write(ral.wdog_ctrl, 0);
    parity_write(ral.intr_state, 3);
    parity_write(ral.wkup_cause, 0);
    parity_write(ral.wkup_count_lo, 0);
    parity_write(ral.wkup_count_hi, 0);
    parity_write(ral.wdog_count, 0);
    parity_write(ral.wkup_thold_lo, 3);
    parity_write(ral.wkup_thold_hi, 0);
    parity_write(ral.wdog_bark_thold, parity_case == 2 ? 6 : 3);
    parity_write(ral.wdog_bite_thold, parity_case == 2 ? 3 : 6);
    if (parity_case == 0) parity_write(ral.wkup_ctrl, 1);
    else                  parity_write(ral.wdog_ctrl, 1);
    cfg.aon_clk_rst_vif.wait_clks(12);
    parity_write(ral.wkup_ctrl, 0);
    parity_write(ral.wdog_ctrl, 0);
    cfg.aon_clk_rst_vif.wait_clks(5);
    csr_utils_pkg::csr_rd(ral.intr_state, intr_value);
    $display("AON_PARITY {\"kind\":\"end\",\"time_ps\":%0.0f,\"case\":%0d,\"intr_state\":%0d}",
             $realtime / 1ps, parity_case, intr_value);
  endtask
endclass
