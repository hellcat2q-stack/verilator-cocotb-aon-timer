# 路线图与阶段门

| 阶段 | 交付 | 阶段门 |
| --- | --- | --- |
| 01 | 源码与环境锁定 | revision、coverage reference、工具版本可追溯 |
| 02 | Verilator build/Cocotb smoke | 固定 RTL 构建、寄存器/复位/时钟 smoke 通过 |
| 03 | Python coverage dictionary | source/sample API 与 4,507 identities 已归档；需 URG bin value detail 才能核验逐项 sample mapping |
| 04 | Cocotb 测试集 | 固定 smoke/jump/prescaler/intr_test 已映射实跑；stress-all/generic tests 待补 |
| 05 | 初始语料 | frozen deterministic pool 已实跑，attempt manifest 与 testcase outcomes 可追溯；无 coverage vector |
| 06 | Bin-by-run matrix | 列数、union、schema 和 hashes 检查通过 |
| 07 | 聚类与调度 | 固定输入回放可重复，算法与后端分离 |
| 08 | 在线闭环 | 新仿真产生反馈，事件日志可审计 |
| 09 | 基线/消融 | 方法使用统一输入、seed、预算、worker 数 |
| 10 | 最终报告 | 独立复核并完整披露限制 |

阶段 01/02 已完成。阶段 03 的 canonical identity 已从原 stage06 矩阵表头提取并校验；取值分区和共享 covergroup sample API 未完成前，不声称生成与 VCS 等价的 coverage vector，也不使用该 vector 做调度对照。
