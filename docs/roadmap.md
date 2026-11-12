# 路线图与阶段门

| 阶段 | 交付 | 阶段门 |
| --- | --- | --- |
| 01 | 源码与环境锁定 | revision、coverage reference、工具版本可追溯 |
| 02 | Verilator build/Cocotb smoke | 固定 RTL 构建、寄存器/复位/时钟 smoke 通过 |
| 03 | Python coverage dictionary | 4507 identities 和采样语义完成核验 |
| 04 | Cocotb 测试集 | sequence 映射、seed 和 checks 可审计 |
| 05 | 初始语料 | 计划冻结，所有 attempts 有 manifest |
| 06 | Bin-by-run matrix | 列数、union、schema 和 hashes 检查通过 |
| 07 | 聚类与调度 | 固定输入回放可重复，算法与后端分离 |
| 08 | 在线闭环 | 新仿真产生反馈，事件日志可审计 |
| 09 | 基线/消融 | 方法使用统一输入、seed、预算、worker 数 |
| 10 | 最终报告 | 独立复核并完整披露限制 |

当前阶段门是 02。阶段 01 只登记源码和工具参考；通过固定源码的 build/smoke 后再开始 coverage 移植和正式语料。
