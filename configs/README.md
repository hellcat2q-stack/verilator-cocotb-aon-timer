# 配置目录

登记源码 revision、工具版本、测试池、seed、预算、worker 和运行协议。正式运行前冻结参数；变化时建立新 schema 或 run ID。

阶段 05 的 `stage05-test-pool.json` 是唯一刺激参数源；`stage05-freeze.json` 保存其规范化文本 SHA-256 和固定源码 revision。改动测试池参数时，必须新建 pool/freeze ID 并重新执行全套校验，不能静默覆盖现有冻结协议。

`coverage_schema.json` 中的 `sample_site_mapping` 登记已接入 raw trace 的采样调用点与未接入项目；只有 `status: COMPLETE`、`complete: true` 且 `unmapped` 为空时，Stage 08 preflight 才会通过采样完整性门。

数组 bin 区间另由 `references/array_bin_ranges.v1.json` 提供 VCS 参考；它是独立的定义证据，不改变当前 raw sample schema 或 Stage 05 冻结 trace。`evidence/stage03_array_bin_partition_audit.json` 已验证源码声明的分区和 Python/Cocotb 端点分类；native Verilator/SystemVerilog covergroup 等价性仍未验证，不能仅凭参考区间开启 coverage 调度。

`conditional-reset-audit.json` 记录固定源码对 `resets_cg` 的条件审计。AON Timer 的 `num_edn` 没有覆盖且保持默认零，因此该 covergroup 在参考配置中标记为 `NOT_APPLICABLE_NUM_EDN_ZERO`；这项结论不替代其余 sample-site 和 identity 映射审计。

`stage09/action-pool.json`、`protocol.json` 和 `freeze.json` 固定本轮 12 个工程动作、四种选择策略、选择 seeds 1/7/19、每策略/seed 24 attempts、固定仿真 seed 1、worker 和时间上限。freeze 记录 pool、protocol 与数组参考文件的 SHA-256；修改参数应建立新 experiment/run，不覆盖本轮输入。
