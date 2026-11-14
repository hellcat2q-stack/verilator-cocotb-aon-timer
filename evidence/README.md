# 证据目录

保存可公开复核的小型摘要：版本、命令、退出码、seed、test 状态、vectors、schema 与 hashes。不要提交 VCS VDB、simv、许可证、token、私有服务器路径或大型完整日志。历史 VCS 数据仅作定义参考。

`stage02_smoke_summary.json` 记录固定源码上的一次 Verilator/Cocotb smoke、seed、PASS 状态和未提交完整日志的 SHA-256。

`stage03_model_unit_summary.json` 记录覆盖源码清单和 Python sample-trace API 的单元测试；它不包含 RTL 仿真结果或 canonical coverage vector。

`canonical_bin_catalog.json` 和 `canonical_bin_ids.txt` 记录原 stage06 矩阵中的 4,507 个唯一 bin identity，仅保留表头派生数据，不包含历史 coverage vectors。

`stage04_sequence_summary.json` 汇总 Cocotb 功能序列映射、固定 revision/工具链、成功 run 和前期失败迭代；不包含 coverage vector。

`stage04_attempts.json` 记录阶段 04 的 source-scan 失败、Cocotb 检查失败以及后续成功 run，避免丢弃失败迭代。

`stage05_initial_corpus.json` 记录冻结 pool 的 SHA-256、seed、源码 revision、工具链、逐 testcase 功能结果、XML/run manifest hashes，以及每个 raw trace 的 SHA-256 和 sample counts；112 条 samples 中有 7 个可确认 named-bin hits。

`stage06_initial/` 保存没有 vector 时的 4,507 列 tri-state scaffold。`stage06_partial/` 保存经验证 raw trace 转换出的 sparse vector 与矩阵审计：7 known hits、4,500 unknown、0 inferred misses；它不是完整 coverage 数据。

`stage07_initial/` 保存原始静态 cluster mapping；`stage07_partial/` 更新 blocker，说明 partial hits 无法推断未覆盖项。聚类不计算 coverage scores，UCB priors 保持为空。

`stage03_raw_trace/` 保存冻结 Stage 05 pool 重新运行生成的 partial source-sample traces 与汇总审计。trace 只证明已接入的 API 运行过，不提供未接入 sample sites、完整 bin mapping 或 vector。

`stage03_array_bin_observations/2026-11-13-seed1-final-v3.json` 使用 VCS 参考区间审计 Stage 05 的 78 条配置样本，记录 40 次正向归属观察、6 个不同数组 identity 和 raw trace hashes。该审计不导入 VCS run hit counts、不生成 Stage 06 vector，也不推断 miss。

`stage05_count_event_v2_verified/` 保存新增只读 RTL counter probe、count-event trace v2 的冻结 suite PASS、4 个原始 trace、结果 XML、运行 manifest 和哈希审计。runner 逐条核验三个计数器 covergroup 的 trace 字段与 RTL 探针，另检查事件类型、倒计时目标与 expiry 边界。`stage06_count_event_v2_verified/` 保留新的 `PARTIAL_VALIDATED` vector 和 4,507 列三态矩阵（13 known hits、4,494 unknown、0 inferred misses）；`stage07_count_event_v2_verified/` 重新记录 78-cluster 确定性映射和 scheduler blocker。最终 readiness 见 `stage08_preflight/2026-11-13-count-event-v2-verified/`；完整 4,507-bin vector、VCS-equivalent count sampling 和在线调度仍未完成。

`configs/conditional-reset-audit.json` 是对 pinned AON Timer/CIP DV 源码的静态审计：`resets_cg` 的实例化和采样均受 `cfg.num_edn` 保护，源码树没有对 `num_edn` 的赋值，因此参考配置将该组标记为 `NOT_APPLICABLE_NUM_EDN_ZERO`。它不提供 VCS/UVM 运行时 trace，也不改变其它 coverage blocker。

`stage03_array_bin_partition_audit.json` 核对 160 个数组 bin 的固定源码声明、VCS 参考区间和 Python/Cocotb 端点分类器；四组数组共 640 个端点探针通过。该证据不代表 Verilator 原生覆盖组执行或 VCS/UVM 时序等价。

`stage08_preflight/2026-11-13-conditional-reset-audited/` 是使用该审计更新 sample-site schema 后的最新门禁输出；它仍明确禁止在线调度。

修复 cadence 过程中的临时 build 和 exploratory run 已清理，没有进入最终 evidence。Stage 06/07/preflight 的最终输入全部来自上述 `stage05_count_event_v2_verified/` run。

`references/bin_definitions.v1.json` 保存 4,507 个 revision-matched 类型级 bin 定义，不包含 run hit data；自动分区和 cross product audits 见该文件。`references/array_bin_ranges.v1.json` 保存由 VCS vectors 表头导入的 160 个数组 bin 参考区间，不含历史 hit counts；Python/Cocotb 分区审计已完成，但 native Verilator/SystemVerilog covergroup 等价性仍未验证。`stage08_preflight/2026-11-13-final-v5/` 记录历史 readiness v2 门禁；当前门禁见 `stage08_preflight/2026-11-13-conditional-reset-audited/`，legacy identity bridge、native covergroup parity、完整 sample APIs 和 exact Stage 06 vectors 尚未完成，因此 scheduler 保持 disabled，且本轮未启动在线 coverage 仿真。

`stage09_comparison/2026-11-14-v1/` 保存 UCB、Random、动作池 round-robin Full 和无 reward 消融的 288 次真实 RTL 对照，含每次 attempt 的 XML、raw sample trace、正向 vector、选择与结果链、comparison CSV、独立 replay audit 和 SHA-256 ledger。288/288 PASS；UCB/Full/消融各确认 175 个正向 identity，Random 为 160–168；unknown 未推断为 misses。160 项数组命中属于 VCS 范围参考映射，Verilator/UVM 采样等价性未验证。
