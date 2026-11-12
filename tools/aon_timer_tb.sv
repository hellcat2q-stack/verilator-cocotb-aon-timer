// Minimal Cocotb bridge for the pinned OpenTitan AON Timer RTL.
module aon_timer_tb (
  input  logic        clk_i,
  input  logic        clk_aon_i,
  input  logic        rst_ni,
  input  logic        rst_aon_ni,
  input  logic        a_valid_i,
  input  logic [2:0]  a_opcode_i,
  input  logic [31:0] a_address_i,
  input  logic [31:0] a_data_i,
  output logic        a_ready_o,
  output logic        d_valid_o,
  output logic        d_error_o,
  output logic [31:0] d_data_o,
  output logic        wkup_req_o,
  output logic        rst_req_o,
  output logic        intr_wkup_o,
  output logic        intr_wdog_o
);
  tlul_pkg::tl_h2d_t tl_i;
  tlul_pkg::tl_d2h_t tl_o;
  prim_alert_pkg::alert_rx_t [aon_timer_reg_pkg::NumAlerts-1:0] alert_rx;
  prim_alert_pkg::alert_tx_t [aon_timer_reg_pkg::NumAlerts-1:0] alert_tx;
  logic nmi_wdog;

  always_comb begin
    tl_i = tlul_pkg::TL_H2D_DEFAULT;
    tl_i.a_valid = a_valid_i;
    tl_i.a_opcode = tlul_pkg::tl_a_op_e'(a_opcode_i);
    tl_i.a_size = 2;
    tl_i.a_address = a_address_i;
    tl_i.a_mask = 4'hf;
    tl_i.a_data = a_data_i;
    tl_i.d_ready = 1'b1;
    tl_i.a_user.cmd_intg = tlul_pkg::get_cmd_intg(tl_i);
    tl_i.a_user.data_intg = tlul_pkg::get_data_intg(a_data_i);
  end

  assign alert_rx[0] = prim_alert_pkg::ALERT_RX_DEFAULT;
  assign a_ready_o = tl_o.a_ready;
  assign d_valid_o = tl_o.d_valid;
  assign d_error_o = tl_o.d_error;
  assign d_data_o = tl_o.d_data;

  aon_timer dut (
    .clk_i,
    .clk_aon_i,
    .rst_ni,
    .rst_aon_ni,
    .tl_i,
    .tl_o,
    .alert_rx_i(alert_rx),
    .alert_tx_o(alert_tx),
    .lc_escalate_en_i(lc_ctrl_pkg::Off),
    .intr_wkup_timer_expired_o(intr_wkup_o),
    .intr_wdog_timer_bark_o(intr_wdog_o),
    .nmi_wdog_timer_bark_o(nmi_wdog),
    .wkup_req_o,
    .aon_timer_rst_req_o(rst_req_o),
    .sleep_mode_i(1'b0)
  );
endmodule
