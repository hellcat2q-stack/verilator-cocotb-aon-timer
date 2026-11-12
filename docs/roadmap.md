# 路线图与阶段门

| 阶段 | 交付 | 阶段门 |
| --- | --- | --- |
| 01 | 源码与环境锁定 | revision、coverage reference、工具版本可追溯 |
| 02 | Verilator build/Cocotb smoke | 固定 RTL 构建、寄存器/复位/时钟 smoke 通过 |
| 03 | Python coverage dictionary | source/sample API、identity catalog 和 intr_test A/D multiplicity 已核对；可观测 CSR/pin 调用已生成 raw traces；完整 value partition/shared sample mapping 待补 |
| 04 | Cocotb 测试集 | 固定 smoke/jump/prescaler/intr_test 已映射实跑并接入 partial raw trace；stress-all/generic tests 待补 |
| 05 | 初始语料 | frozen deterministic pool 已实跑，attempt manifest 记录并校验 trace hashes/sample counts；无 coverage vector |
| 06 | Bin-by-run matrix | 三态矩阵/identity/hash 审计已验证；真实 run vectors 待阶段 03 mapping 与 Cocotb sample 接入 |
| 07 | 聚类与调度 | canonical identity clustering 和固定输入回放已实现；coverage score/UCB 输入等待真实 vectors |
| 08 | 在线闭环 | 新仿真产生反馈，事件日志可审计 |
| 09 | 基线/消融 | 方法使用统一输入、seed、预算、worker 数 |
| 10 | 最终报告 | 独立复核并完整披露限制 |

阶段 01/02 已完成。阶段 03 的 canonical identity 已从原 stage06 矩阵表头提取并校验；取值分区和共享 covergroup sample API 未完成前，不声称生成与 VCS 等价的 coverage vector，也不使用该 vector 做调度对照。

阶段 06 工具使用 `1/0/?` 表示已知命中/已知未命中/未知；当前阶段 05 corpus 没有 vector，故 scaffold 的 4,507 格均为未知。阶段 06 最终阶段门仍等待采样映射与真实 Cocotb coverage data。

阶段 07 可以仅根据 canonical identity 生成静态 cluster mapping；缺少已验证 run vectors 时，自信息、cluster prior 和 UCB state 必须保持 unavailable，不能作为真实 coverage feedback。
