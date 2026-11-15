# 阶段 10：最终复核与报告

状态（2026-11-15）：**Stage 09 工程结果已独立复核；原始 URG 标签布局已恢复并检出旧行号映射错误；完整论文 full coverage 仍不可报告。**

## 复核结论

本次可报告的数值是 Stage 09 UCB（selection seed 1）确认观察到的 175/4,507 个 canonical identities，即目录比例 3.8828%。这只是已确认正向 identity 占目录的比例，不是 full coverage rate。剩余 4,332 个 identities 是 unknown，不能据此当作 miss 或未覆盖 bins。

4,507 canonical identities 和 4,525 URG dashboard reference 是两个不同统计口径，不能互换。Stage 09 的 160 个数组 identity 来自已登记的 VCS 分区参考；目前没有证明 Verilator/Cocotb 的采样与原生 UVM/VCS 等价。

Stage 09 独立 replay audit 通过，288/288 个 RTL testcase PASS，证据目录的 1,443 个文件均通过 SHA-256 ledger 校验。full-paper preflight 仍为 `BLOCKED_PREREQUISITES_INCOMPLETE`：仅 341/4,507 legacy identities 可按标签直接匹配，exact vector matrix 不可用，sample-site mapping 未完整，Stage 07 paper scheduler 未允许。

机器可读审查记录及其 SHA-256 sidecar：[review.json](../evidence/stage10_final_review/2026-11-14-v1/review.json)、[review.json.sha256](../evidence/stage10_final_review/2026-11-14-v1/review.json.sha256)。Stage 09 的逐次运行结果见[汇总](../evidence/stage09_comparison/2026-11-14-v1/summary.json)与[对照表](../evidence/stage09_comparison/2026-11-14-v1/comparison.csv)。

映射诊断入口为 tools/audit_canonical_identity_candidates.py。它报告 canonical labels 对 frozen source-definition 的 exact/range candidate 关系，不创建新的 coverage credit。运行命令：python3 tools/audit_canonical_identity_candidates.py --output evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json。

2026-11-15 候选审计将 4,507 个 canonical labels 分类为：341 个直接类型标签匹配、2 个精确值区间候选、2,074 个组合值区间候选、2,080 个 cross/展开标签未决，以及 10 个其他值标签未决。精确/组合区间仍有 legacy occurrence index 未决；标签匹配也不证明 sample-site 或 UVM/VCS 采样等价。该审计授予 0 个 coverage credit，不把未知项推断为 miss，因此 175 个正向 identity、4,332 个 unknown 和 `full_coverage_rate_percent: null` 均保持不变。报告和 SHA-256 sidecar：[identity-candidates.json](../evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json)、[identity-candidates.json.sha256](../evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json.sha256)。

在 WSL Ubuntu 24.04 的现有项目虚拟环境中，最新全仓单测 105/105 通过。仿真工具链保持 Verilator 5.020、Cocotb 1.9.2、lowRISC FuseSoC 0.5.dev0、Edalize 0.4.0；新增 HTML 审计依赖另记在 `configs/stage10-requirements.txt`。full coverage 门禁继续保持 blocked。

本机原论文仓库 Stage 06 转换器（旧仓库 commit `ff59c4a`，SHA-256 `31d9cf6e3c298409436be2888098ff7a9d888cd09b070bd27f0c3ddc12009506`）显示，legacy identity 最后一段由压缩 URG 行的 `offset` 产生，之后 CSV 列按 `bin_keys` 排序；`bin_manifest.json` 只登记最终列和计数，没有保存每列的展开 bin 名。该 manifest SHA-256 为 `cbc7e64a0004f0387f16f36e24edc2442a8225b3179fae6c673fe3ac84c28e3e`，其中登记的 CSV SHA-256 为 `71c02be6b80cb63973eeb96b26340f7e1d1ae2246674d148774c39c616ff1e94`。前一轮本机查找未找到对应 HTML，本轮已从学校服务器恢复。2,076 个 auto/value-range identities 的顺序候选保留为历史诊断，不允许直接提升为映射。其输入哈希见 [ordinal-range-candidates.json](../evidence/stage10_final_review/2026-11-15-v2/ordinal-range-candidates.json) 及其 [SHA-256 sidecar](../evidence/stage10_final_review/2026-11-15-v2/ordinal-range-candidates.json.sha256)。

已从服务器 `stage06_conversion_20261101T_v10` 恢复 `original_g0/g1/g10/g20/g30` 的 80 份 `grp*.html`，逐文件核验服务器 SHA-256。VCS compiler/runtime 为 `P-2019.06-SP1_Full64`，URG 为 `P-2019.06-SP1`。首份报告能准确重建 4,507 个冻结列；对另外四份报告，旧转换器的按位置对齐分别出现 126、114、83、236 处可确认的语义冲突，合计 559 处（不是 559 个去重 bin）。例如首份报告的 `wdog_regwen_cp` 行序为值 1、值 0，`original_g1` 为值 0、值 1；旧逻辑仍按原位置写入，造成两列互换。即便 bin 总数和总命中数相同，也不能证明逐列身份一致。

新增审计器 `tools/audit_legacy_urg_layouts.py` 按明确 bin 名或 singleton 值对齐，可在每份对照报告中匹配 345 个明确变量 identity，拒绝压缩区间、wildcard cross、重复名字及缺失身份；这不是采样等价或完整映射。压缩行仍不暴露逐 bin 次序，因此 v2 顺序候选继续不获 credit。可公开重放的标签布局、来源哈希、恢复记录和错误反例见 [新证据目录](../evidence/stage10_legacy_urg_layout/2026-11-15-v1/README.md)。本轮没有启动 VCS 或 RTL 仿真，没有导出历史 hit counts；Stage 09 的 175 个正向观察来源于本仓库 Cocotb traces，结果不因此增加。

后续先以固定源码定义中的 `definition_id` 建立稳定分类器，再把 Cocotb raw samples 分类并输出新 schema 的向量；对旧 CSV 仅保留能够逐项验证的明确身份关联。完整覆盖统计还需补齐 shared DV/TL sample-site 和采样语义。旧 39-run CSV 的按列语义需要单独修复，不能拿它的行号作为新 coverage classifier 的真值。

## 复核命令

在 WSL Ubuntu 仓库根目录运行：

```bash
python3 tools/audit_stage09_comparison.py \
  --evidence-dir evidence/stage09_comparison/2026-11-14-v1

python3 -m unittest discover -s tests -q

# 从公开的定义标签布局重放；不需要访问学校服务器或安装 HTML parser
python3 tools/audit_legacy_urg_layouts.py \
  --layouts evidence/stage10_legacy_urg_layout/2026-11-15-v1/layouts.json \
  --output-dir build/stage10-legacy-urg-replay
```

该审计重放现存 Stage 09 XML、trace、向量、选择决策与 hashes；它不是新的 UVM/VCS 仿真，也不补全 bin/sample 映射。当前 full coverage rate 保持 `null / not reportable`，直到完整身份映射、采样点语义、exact vectors 和 VCS/UVM sampling comparison 有证据支持。
