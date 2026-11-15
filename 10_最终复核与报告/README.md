# 阶段 10：最终复核与报告

状态（2026-11-15）：**Stage 09 工程结果已独立复核；canonical identity 候选诊断完成；完整论文 full coverage 仍不可报告。**

## 复核结论

本次可报告的数值是 Stage 09 UCB（selection seed 1）确认观察到的 175/4,507 个 canonical identities，即目录比例 3.8828%。这只是已确认正向 identity 占目录的比例，不是 full coverage rate。剩余 4,332 个 identities 是 unknown，不能据此当作 miss 或未覆盖 bins。

4,507 canonical identities 和 4,525 URG dashboard reference 是两个不同统计口径，不能互换。Stage 09 的 160 个数组 identity 来自已登记的 VCS 分区参考；目前没有证明 Verilator/Cocotb 的采样与原生 UVM/VCS 等价。

Stage 09 独立 replay audit 通过，288/288 个 RTL testcase PASS，证据目录的 1,443 个文件均通过 SHA-256 ledger 校验。full-paper preflight 仍为 `BLOCKED_PREREQUISITES_INCOMPLETE`：仅 341/4,507 legacy identities 可按标签直接匹配，exact vector matrix 不可用，sample-site mapping 未完整，Stage 07 paper scheduler 未允许。

机器可读审查记录及其 SHA-256 sidecar：[review.json](../evidence/stage10_final_review/2026-11-14-v1/review.json)、[review.json.sha256](../evidence/stage10_final_review/2026-11-14-v1/review.json.sha256)。Stage 09 的逐次运行结果见[汇总](../evidence/stage09_comparison/2026-11-14-v1/summary.json)与[对照表](../evidence/stage09_comparison/2026-11-14-v1/comparison.csv)。

映射诊断入口为 tools/audit_canonical_identity_candidates.py。它报告 canonical labels 对 frozen source-definition 的 exact/range candidate 关系，不创建新的 coverage credit。运行命令：python3 tools/audit_canonical_identity_candidates.py --output evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json。

2026-11-15 候选审计将 4,507 个 canonical labels 分类为：341 个直接类型标签匹配、2 个精确值区间候选、2,074 个组合值区间候选、2,080 个 cross/展开标签未决，以及 10 个其他值标签未决。精确/组合区间仍有 legacy occurrence index 未决；标签匹配也不证明 sample-site 或 UVM/VCS 采样等价。该审计授予 0 个 coverage credit，不把未知项推断为 miss，因此 175 个正向 identity、4,332 个 unknown 和 `full_coverage_rate_percent: null` 均保持不变。报告和 SHA-256 sidecar：[identity-candidates.json](../evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json)、[identity-candidates.json.sha256](../evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json.sha256)。

在 WSL Ubuntu 24.04 的现有项目虚拟环境中，全仓单测 98/98 通过。工具链已满足仓库锁定版本（Verilator 5.020、Cocotb 1.9.2、lowRISC FuseSoC 0.5.dev0、Edalize 0.4.0），无需额外安装缺失的项目包。下一步需要取得 canonical bin 展开与 legacy occurrence index 的可验证映射，并补齐 sample-site 与 VCS/UVM 同步采样证据；在这些材料齐备前，full coverage 门禁继续保持 blocked。

本机原论文仓库 Stage 06 转换器（旧仓库 commit `ff59c4a`，SHA-256 `31d9cf1e3c298409436be2888098ff7a9d888cd09b070bd27f0c3ddc12009506`）显示，legacy identity 最后一段由压缩 URG 行的 `offset` 产生，之后 CSV 列按 `bin_keys` 排序；`bin_manifest.json` 只登记最终列和计数，没有保存每列的展开 bin 名。该 manifest SHA-256 为 `cbc7e64a0004f0387f16f36e24edc2442a8225b3179fae6c673fe3ac84c28e3e`，其中登记的 CSV SHA-256 为 `71c02be6b80cb63973eeb96b26340f7e1d1ae2246674d148774c39c616ff1e94`。当前本机副本未找到对应的 `grp*.html` 页面或 Stage 06 cumulative XML。对 2,076 个 auto/value-range identities，值域候选数量、连续分区数量和每组 `0..N-1` occurrence offsets 可以一一配对；这只是顺序候选，不证明 VCS bin ordinal 与源定义相同。工具验证后的输入哈希见 [ordinal-range-candidates.json](../evidence/stage10_final_review/2026-11-15-v2/ordinal-range-candidates.json) 及其 [SHA-256 sidecar](../evidence/stage10_final_review/2026-11-15-v2/ordinal-range-candidates.json.sha256)。

其余 cross 列仍无法按标签定位：watchdog bark/bite 两组分别有 512 个 `name:*X*` identity，wakeup cross 有 1,022 个 identity 共用一个 `*X*` 标签。下一步需要恢复生成该矩阵的原始 URG `grp*.html` 或 VCS cumulative XML/VDB，并记录 VCS/URG 版本，验证 offset 到 source bin 的顺序；随后仍需将对应 sample-site 同 Cocotb trace 做事件级对照。候选映射不改变 full coverage readiness 或 175/4,507 正向观察结果。

## 复核命令

在 WSL Ubuntu 仓库根目录运行：

```bash
python3 tools/audit_stage09_comparison.py \
  --evidence-dir evidence/stage09_comparison/2026-11-14-v1

python3 -m unittest discover -s tests -q
```

该审计重放现存 Stage 09 XML、trace、向量、选择决策与 hashes；它不是新的 UVM/VCS 仿真，也不补全 bin/sample 映射。当前 full coverage rate 保持 `null / not reportable`，直到完整身份映射、采样点语义、exact vectors 和 VCS/UVM sampling comparison 有证据支持。
