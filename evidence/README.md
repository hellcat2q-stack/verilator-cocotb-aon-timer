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
