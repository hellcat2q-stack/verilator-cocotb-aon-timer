# 阶段 04：Cocotb测试序列移植

状态：确定性功能序列初版已通过，并接入可观测 CSR/pin partial raw trace；随机 stress-all 与通用 CSR/memory/error 测试待后续阶段。

## 官方场景映射

| 官方场景 | Cocotb testcase | 当前检查 | 差异 |
| --- | --- | --- | --- |
| `aon_timer_smoke_vseq` | `aon_timer_smoke_sequence` | wakeup interrupt、watchdog bark、bite reset、`INTR_STATE`、`WKUP_CAUSE` | 官方随机阈值固定为 3/2/5；没有 sleep/LC escalation 随机化 |
| `aon_timer_jump_vseq` | `aon_timer_jump_sequence` | 两计数器启动、阈值下调到当前 count 以下后的 wakeup/bark/bite 输出 | 固定初始 count/threshold；未覆盖 full-width 随机边界 |
| `aon_timer_prescaler_vseq` | `aon_timer_prescaler_sequence` | prescaler 0 和 3 的 expiry 周期对比 | 只测两个固定值，未在运行中多次随机切换 |
| inherited `intr_test` common sequence | `aon_timer_intr_test_sequence` | 两个 interrupt test bit、状态位和 W1C 清除 | 固定双位写入 |
| `aon_timer_stress_all_vseq` | 未实现 | — | 15–20 个随机子序列和 reset 注入留到阶段 05/08 |

运行入口：`tools/run_stage04_tests.sh`。runner 核验固定源码 revision、工具版本并解析 Cocotb `results.xml`；即使 make 返回 0，只要测试失败也会记录失败。运行 manifest 保存 seed、test counts、状态和仿真时长。

runner 已将 `CoverageTrace` 接入可观测的 CSR 与 AON pin 事件，保存每个 testcase 的 partial raw sample trace。Stage 05 manifest 会校验并汇总 trace hashes 和 sample counts。由于 count-event backdoor samples、reset group、共享组和 bin value partition 尚未完成，本阶段仍不生成 canonical coverage vector，也不声称与 VCS/URG 等价。

实跑记录和失败迭代摘要见 [`实施记录.md`](实施记录.md)，最终摘要见 [`evidence/stage04_sequence_summary.json`](../evidence/stage04_sequence_summary.json)。
