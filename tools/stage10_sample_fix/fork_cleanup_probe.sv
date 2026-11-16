// A/B probe of the original and repaired reset isolation topology.
module fork_cleanup_probe;
  timeunit 1ns;
  timeprecision 1ps;
  bit reset_active = 0;
  event tick;
  int original_count = 0;
  int isolated_count = 0;

  task automatic original_controller();
    forever begin
      wait (!reset_active);
      fork : original_isolation_fork
        fork
          wait (reset_active);
          forever begin
            @(tick);
            original_count++;
          end
        join_any
        disable fork;
      join
    end
  endtask

  task automatic isolated_controller();
    forever begin
      wait (!reset_active);
      fork
        begin : isolated_child
          fork
            wait (reset_active);
            forever begin
              @(tick);
              isolated_count++;
            end
          join_any
          disable fork;
        end
      join
    end
  endtask

  initial begin
    fork
      original_controller();
      isolated_controller();
      begin
        #1ns;
        reset_active = 1;
        #1ns;
        reset_active = 0;
        repeat (5) begin
          #10ns;
          -> tick;
        end
        #1ns;
        $display("FORK_CLEANUP_PROBE {\"tick_count\":5,\"original_count\":%0d,\"isolated_count\":%0d}",
                 original_count, isolated_count);
        $finish;
      end
    join
  end
endmodule
