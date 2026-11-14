# 阶段 10：最终复核与报告

状态（2026-11-14）：**Stage 09 工程结果已独立复核并形成报告；完整论文 full coverage 仍不可报告。**

## 复核结论

本次可报告的数值是 Stage 09 UCB（selection seed 1）确认观察到的 175/4,507 个 canonical identities，即目录比例 3.8828%。这只是已确认正向 identity 占目录的比例，不是 full coverage rate。剩余 4,332 个 identities 是 unknown，不能据此当作 miss 或未覆盖 bins。

4,507 canonical identities 和 4,525 URG dashboard reference 是两个不同统计口径，不能互换。Stage 09 的 160 个数组 identity 来自已登记的 VCS 分区参考；目前没有证明 Verilator/Cocotb 的采样与原生 UVM/VCS 等价。

Stage 09 独立 replay audit 通过，288/288 个 RTL testcase PASS，证据目录的 1,443 个文件均通过 SHA-256 ledger 校验。full-paper preflight 仍为 `BLOCKED_PREREQUISITES_INCOMPLETE`：仅 341/4,507 legacy identities 可按标签直接匹配，exact vector matrix 不可用，sample-site mapping 未完整，Stage 07 paper scheduler 未允许。

机器可读审查记录及其 SHA-256 sidecar：[review.json](../evidence/stage10_final_review/2026-11-14-v1/review.json)、[review.json.sha256](../evidence/stage10_final_review/2026-11-14-v1/review.json.sha256)。Stage 09 的逐次运行结果见[汇总](../evidence/stage09_comparison/2026-11-14-v1/summary.json)与[对照表](../evidence/stage09_comparison/2026-11-14-v1/comparison.csv)。

## 复核命令

在 WSL Ubuntu 仓库根目录运行：

```bash
python3 tools/audit_stage09_comparison.py \
  --evidence-dir evidence/stage09_comparison/2026-11-14-v1

python3 -m unittest discover -s tests -q
```

该审计重放现存 Stage 09 XML、trace、向量、选择决策与 hashes；它不是新的 UVM/VCS 仿真，也不补全 bin/sample 映射。当前 full coverage rate 保持 `null / not reportable`，直到完整身份映射、采样点语义、exact vectors 和 VCS/UVM sampling comparison 有证据支持。
