# 阶段 06：覆盖矩阵与审计

状态：矩阵格式、审计工具与初始 scaffold 已完成；实际 bin hits/misses 未采集，阶段门未通过。

## 矩阵契约

- 列顺序严格来自 `references/canonical_bin_ids.txt`，共 4,507 个 canonical identities。
- 每格使用三态：`1` 表示已观测到 hit，`0` 表示已观测到 miss，`?` 表示未采集或语义未映射。未知不自动变成 0。
- 每个失败 run 保留一行，但所有 bin cell 置为 `?`，失败运行不获得覆盖奖励。
- 输入 vector 必须匹配 run、源码 revision、coverage schema、冻结 pool/seed、canonical identity list hash，并标明 `PARTIAL_VALIDATED` 或 `EXACT_VALIDATED`；不接受猜测身份或孤立 run vector。
- 完整矩阵只在全部 4,507 列有已验证 0/1 且映射状态 exact 时成立。

## 运行

```bash
python3 tools/stage06_matrix.py \
  --corpus-manifest evidence/stage05_initial_corpus.json \
  --vector-dir /path/to/validated-run-vectors \
  --out-dir evidence/stage06
```

vector 文件可选；放在 `vector-dir/<run_id>.json`。当前阶段 05 尚未导出 coverage vectors，因此可省略 `--vector-dir`，工具会生成带未知单元的矩阵并明确报告 incomplete。

## 当前结果

初始审计见 [`evidence/stage06_initial/coverage_matrix_audit.json`](../evidence/stage06_initial/coverage_matrix_audit.json)，矩阵见 [`coverage_bin_by_run.csv`](../evidence/stage06_initial/coverage_bin_by_run.csv)。CSV 包含 12 个 run metadata 字段和 4,507 个 bin identity 字段；当前唯一 run 的 4,507 个值全为 `?`。因此 union 为 0 个已知 hit、0 个已知 miss、4,507 个 unknown。该结果只验证矩阵结构和审计逻辑，不是覆盖采集成功。

精确 coverage mapping 仍需补全阶段 03 中的 array/auto-bin 取值分区和共享 coverage sample API，并把 `CoverageTrace` 接入实际 Cocotb sample 时序。完成前不得将本 scaffold 用于 coverage-driven 调度或覆盖率对比。
