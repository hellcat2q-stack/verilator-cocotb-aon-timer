# UVM/VCS 控制事件形状对照 v2

本轮复用四次短运行的 21 条事件摘要，没有新增仿真。`audit_uvm_vcs_timing.py` 实际调用 `TimerSampleScheduler.tick()`，以观测到的 count 数作为假定 countdown 长度，从首个 count 对齐比较事件顺序和相对间隔。报告登记工具、Python 模型、来源 JSON 和事件摘要的哈希，full timing parity 始终为 false。

| 运行 | 主 count 数 | 能确认的控制事件特征 |
| --- | --- | --- |
| wakeup smoke | 8 | count 顺序、相邻间隔 5 μs、最后 count 与 expiry 同时 |
| wakeup jump | 5 | count 顺序、相邻间隔 5 μs、最后 count 与 expiry 同时 |
| watchdog bark | 1 | count 先于同一时刻的 expiry；无法测量 count 间隔 |
| watchdog bite | 1 | count 先于同一时刻的 expiry；无法测量 count 间隔 |

bark/bite 中伴随的另一 watchdog count 仍保留，但不用于补足主 group 验证。四份日志均报告 UVM_ERROR/UVM_FATAL 为 0、TEST PASSED CHECKS；本轮未重新采集原进程退出码，因此该字段为 null。完整日志、simv 和私有绝对路径均未提交。

UVM_HIGH 行位于 `-> sample_coverage` 之前，不能证明实际 covergroup 的调用次数。连续同时间点触发可能受 SV named-event 调度影响；需要在实际 `.sample()` 分支记录时间、调用次序和全部实参，才能核实。现有日志也没有 enable 起点，因此 4 个 startup clocks 仍是 Python 模型假定，未得到独立测量。Cocotb 与 VCS 没有运行相同刺激下的逐样本对照。

源码核验还发现：固定 revision 的 scoreboard SHA-256 为 `b6534a47…`，现成 simv 所在源码树的 scoreboard 为 `cc92b1dc…`。差异包括 reset 子进程清理、wakeup 高位 CSR 读取修正，以及 wakeup/watchdog 中断检查等待窗口。当前源码树的哈希不等于二进制完整编译来源证明，因此报告保留 `build_source_revision_verified: false`。这四次运行只作为诊断证据，不作为固定版本的采样等价证据。详见 [provenance.json](provenance.json)。

```bash
python3 tools/audit_uvm_vcs_timing.py \
  --evidence-dir evidence/stage10_uvm_vcs_timing/2026-11-16-v2 \
  --output build/stage10-uvm-control-shape-replay.json
```

当前结果为 `count_event_shape_comparison_complete: true`、`independent_uvm_vcs_timing_comparison_complete: false`、`coverage_credit_granted: 0`。下一步要求见 [逐采样对照计划](../../../configs/stage10-uvm-sample-parity-plan.json)。
