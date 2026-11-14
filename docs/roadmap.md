# 路线图与阶段门

| 阶段 | 交付 | 阶段门 |
| --- | --- | --- |
| 01 | 源码与环境锁定 | revision、coverage reference、工具版本可追溯 |
| 02 | Verilator build/Cocotb smoke | 固定 RTL 构建、寄存器/复位/时钟 smoke 通过 |
| 03 | Python coverage dictionary | count-event v2 已接 RTL counter probe；13 个 identity 可确认命中；完整 identity、shared sample mapping 与 UVM/VCS 对照待补 |
| 04 | Cocotb 测试集 | 固定 smoke/jump/prescaler/intr_test 已映射实跑并接入 partial raw trace；stress-all/generic tests 待补 |
| 05 | 初始语料 | frozen deterministic pool、seed 1 已实跑，4/4 PASS；count-event v2 suite 有 201 条 raw samples、13 个可确认 identity hits |
| 06 | Bin-by-run matrix | count-event v2 partial vector：13 hits、4,494 unknown、0 推断 miss；完整矩阵阶段门未通过 |
| 07 | 聚类与调度 | canonical identity clustering 和固定输入回放已实现；已知 sparse hits 仍不能确认 misses/remaining bins，coverage score/UCB 保持 blocked |
| 08 | 在线闭环 | 独立 positive-hit pilot：12 次真实仿真、4 warmup + 8 testcase UCB 决策、12/12 PASS、585 样本；完整论文闭环仍受 Stage 03/06/07 限制 |
| 09 | 基线/消融 | 方法使用统一输入、seed、预算、worker 数 |
| 10 | 最终报告 | 独立复核并完整披露限制 |

阶段 01/02 已完成。其余阶段可以并行推进，但不能将工程 pilot 与完整论文复现混为一谈。160 个数组 bin 的 VCS 参考区间只提供边界参考；Python/Cocotb live 采样、legacy identity 和 shared coverage 尚待核验，不能宣称覆盖等价。

阶段 06 保持 `1/0/?` 三态。最新 suite union 为 13 hit、0 miss、4,494 unknown；Stage 08 pilot 同样只使用正向命中奖励，不将 unknown 解释为未命中。

阶段 07 的论文自信息和 residual cluster prior 需要完整语义，继续保持 unavailable。Stage 08 的 `testcase_ucb_positive_novelty_v1` 是另行登记的工程策略：只统计已完成 run 的新增正向命中，不需要推断 misses；并非论文 cluster UCB。

接下来依次完成：参数化刺激与 live coverage 扩展 → 信息评分/cluster UCB → 第 09 步统一预算的 Random/Full/消融 → 第 10 步独立复核。原生 SystemVerilog covergroup 不是 Python/Cocotb 在线闭环的前置条件。
