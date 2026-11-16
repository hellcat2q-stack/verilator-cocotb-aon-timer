// Probe VCS event-control behavior independently of UVM and the timer RTL.
module event_wait_probe;
  timeunit 1ns;
  timeprecision 1ps;
  event tick;
  int property_wait_count = 0;
  int named_event_wait_count = 0;
  initial begin
    fork
      forever begin
        @(tick.triggered);
        property_wait_count++;
      end
      forever begin
        @(tick);
        named_event_wait_count++;
      end
      begin
        repeat (5) begin
          #10ns;
          -> tick;
        end
        #1ns;
        $display("EVENT_WAIT_PROBE {\"producer_count\":5,\"property_wait_count\":%0d,\"named_event_wait_count\":%0d}",
                 property_wait_count, named_event_wait_count);
        $finish;
      end
    join
  end
endmodule
