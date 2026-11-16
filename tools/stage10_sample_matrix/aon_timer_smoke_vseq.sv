// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
// This replacement is installed only in the isolated stage10 matrix source tree.
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

  task parity_sleep(bit value);
    // Drive after the current AON edge, matching the sequence's clocking-block
    // return semantics and making the synchronizer's first sample unambiguous.
    #1ps;
    cfg.sleep_vif.drive(value);
    $display("AON_PARITY {\"kind\":\"sleep\",\"time_ps\":%0.0f,\"value\":%0d}",
             $realtime / 1ps, value);
  endtask

  task parity_initialize(int parity_case);
    parity_write(ral.wkup_ctrl, 0);
    parity_write(ral.wdog_ctrl, 0);
    parity_write(ral.intr_state, 3);
    parity_write(ral.wkup_cause, 0);
    parity_write(ral.wkup_count_lo, 0);
    parity_write(ral.wkup_count_hi, 0);
    parity_write(ral.wdog_count, 0);
    parity_write(ral.wkup_thold_lo, (parity_case == 4) ? 2 : 3);
    parity_write(ral.wkup_thold_hi, 0);
    parity_write(ral.wdog_bark_thold, (parity_case == 2) ? 6 : 3);
    parity_write(ral.wdog_bite_thold, (parity_case == 2) ? 3 : 6);
  endtask

  virtual task body();
    int parity_case = 0;
    uvm_reg_data_t intr_value;
    void'($value$plusargs("aon_parity_case=%d", parity_case));
    `DV_CHECK_FATAL(parity_case inside {[0:7]})
    cfg.lc_escalate_en_vif.drive(0);
    parity_sleep(0);
    $display("AON_PARITY {\"kind\":\"begin\",\"time_ps\":%0.0f,\"case\":%0d}",
             $realtime / 1ps, parity_case);
    parity_initialize(parity_case);

    case (parity_case)
      0: begin
        parity_write(ral.wkup_ctrl, 1);
        cfg.aon_clk_rst_vif.wait_clks(12);
      end
      1: begin
        parity_write(ral.wdog_ctrl, 1);
        cfg.aon_clk_rst_vif.wait_clks(12);
      end
      2: begin
        parity_write(ral.wdog_ctrl, 1);
        cfg.aon_clk_rst_vif.wait_clks(12);
      end
      3: begin
        parity_write(ral.intr_test, 3);
        csr_utils_pkg::csr_rd(ral.intr_state, intr_value);
        `DV_CHECK_EQ(intr_value[1:0], 2'b11)
        parity_write(ral.intr_state, 3);
        csr_utils_pkg::csr_rd(ral.intr_state, intr_value);
        `DV_CHECK_EQ(intr_value[1:0], 2'b00)
      end
      4: begin
        parity_write(ral.wkup_ctrl, 5);
        cfg.aon_clk_rst_vif.wait_clks(24);
      end
      5: begin
        parity_write(ral.wkup_thold_lo, 10);
        parity_write(ral.wkup_ctrl, 1);
        cfg.aon_clk_rst_vif.wait_clks(7);
        // Exercise live threshold/count updates without moving the threshold
        // behind the current count (which makes the reference scoreboard's
        // expiry prediction race the interrupt pin).
        parity_write(ral.wkup_thold_lo, 20);
        parity_write(ral.wkup_count_lo, 0);
        cfg.aon_clk_rst_vif.wait_clks(4);
        parity_write(ral.wkup_ctrl, 0);
        parity_write(ral.intr_state, 3);
        parity_write(ral.wkup_thold_lo, 3);
        parity_write(ral.wkup_count_lo, 0);
        parity_write(ral.wkup_ctrl, 1);
        cfg.aon_clk_rst_vif.wait_clks(12);
      end
      6: begin
        parity_write(ral.wkup_thold_lo, 10);
        parity_write(ral.wkup_ctrl, 1);
        cfg.aon_clk_rst_vif.wait_clks(7);
        // Avoid asserting asynchronous reset in the same time slot as the
        // AON sampling edge; the reference scoreboard samples that edge first.
        #1ps;
        apply_reset("HARD");
        parity_initialize(6);
        parity_write(ral.wkup_thold_lo, 2);
        parity_write(ral.wkup_ctrl, 1);
        cfg.aon_clk_rst_vif.wait_clks(16);
      end
      7: begin
        parity_write(ral.wdog_bark_thold, 20);
        parity_write(ral.wdog_bite_thold, 30);
        parity_write(ral.wdog_ctrl, 3);
        cfg.aon_clk_rst_vif.wait_clks(7);
        parity_sleep(1);
        cfg.aon_clk_rst_vif.wait_clks(8);
        // Stop the first scorekeeper while still asleep. Restart from a known
        // count after wake so the post-sleep sample stream is bounded and
        // reproducible across simulators.
        parity_write(ral.wdog_ctrl, 0);
        cfg.aon_clk_rst_vif.wait_clks(4);
        parity_sleep(0);
        cfg.aon_clk_rst_vif.wait_clks(4);
        parity_write(ral.wdog_count, 0);
        parity_write(ral.wdog_bark_thold, 3);
        parity_write(ral.wdog_bite_thold, 6);
        parity_write(ral.wdog_ctrl, 3);
        cfg.aon_clk_rst_vif.wait_clks(12);
      end
      default: `DV_CHECK_FATAL(0)
    endcase

    parity_write(ral.wkup_ctrl, 0);
    parity_write(ral.wdog_ctrl, 0);
    cfg.aon_clk_rst_vif.wait_clks(5);
    csr_utils_pkg::csr_rd(ral.intr_state, intr_value);
    $display("AON_PARITY {\"kind\":\"end\",\"time_ps\":%0.0f,\"case\":%0d,\"intr_state\":%0d}",
             $realtime / 1ps, parity_case, intr_value);
  endtask
endclass
