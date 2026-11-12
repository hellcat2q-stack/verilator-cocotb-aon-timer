# 证据目录

保存可公开复核的小型摘要：版本、命令、退出码、seed、test 状态、vectors、schema 与 hashes。不要提交 VCS VDB、simv、许可证、token、私有服务器路径或大型完整日志。历史 VCS 数据仅作定义参考。

`stage02_smoke_summary.json` 记录固定源码上的一次 Verilator/Cocotb smoke、seed、PASS 状态和未提交完整日志的 SHA-256。

`stage03_model_unit_summary.json` 记录覆盖源码清单和 Python sample-trace API 的单元测试；它不包含 RTL 仿真结果或 canonical coverage vector。

`canonical_bin_catalog.json` 和 `canonical_bin_ids.txt` 记录原 stage06 矩阵中的 4,507 个唯一 bin identity，仅保留表头派生数据，不包含历史 coverage vectors。

`stage04_sequence_summary.json` 汇总 Cocotb 功能序列映射、固定 revision/工具链、成功 run 和前期失败迭代；不包含 coverage vector。

`stage04_attempts.json` 记录阶段 04 的 source-scan 失败、Cocotb 检查失败以及后续成功 run，避免丢弃失败迭代。

`stage05_initial_corpus.json` 记录冻结 pool 的 SHA-256、seed、源码 revision、工具链、逐 testcase 功能结果与 XML/run manifest hashes；它不是 bin-by-run coverage 数据。

`stage06_initial/` 保存从阶段 05 功能语料构建的 4,507 列 tri-state scaffold 和审计。当前所有 bin 值均为 unknown，表示尚无 coverage vector。
