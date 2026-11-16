# 已由 v2 替代

本目录保留初版证据。v1 的 `independent_uvm_vcs_timing_comparison_complete: true` 表述过强，不能用于证明完整时序等价；初版审计也没有实际调用 `TimerSampleScheduler`。这些问题已在 [v2](../2026-11-16-v2/README.md) 修正。旧日志摘要与哈希未改动。

这些 UVM_HIGH 行记录的是 count/expiry 触发处，未记录 covergroup 实际调用、采样元组或 enable 时刻。wakeup 相邻 count 间隔为 5,000,000 ps，即 5 μs。bark/bite 各只有一个主 count，无法测量 cadence。现成 simv 所在目录的 scoreboard 也与固定 revision 的文件哈希不同，不能据此认定固定版本的采样等价。
