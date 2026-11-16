# 阶段 10：最终复核与报告

状态（2026-11-16）：**Stage 09 工程结果已独立复核；source-definition 分类 v2、identity bridge、sample-site、历史 vector header、VCS/Python 数组边界与局部 UVM/VCS count-event shape 对照均完成；full 仿真启动门禁仍 blocked，full coverage 仍不可报告。**

## 复核结论

本次可报告的数值是 Stage 09 UCB（selection seed 1）确认观察到的 175/4,507 个 canonical identities，即目录比例 3.8828%。这只是已确认正向 identity 占目录的比例，不是 full coverage rate。新增的 UVM/VCS 证据只统计 21 条短运行 count/expiry 事件，不能转化为 canonical bin 命中数。剩余 4,332 个 identities 是 unknown，不能据此当作 miss 或未覆盖 bins。

4,507 canonical identities 和 4,525 URG dashboard reference 是两个不同统计口径，不能互换。Stage 09 的 160 个数组 identity 来自已登记的 VCS 分区参考；目前没有证明 Verilator/Cocotb 的采样与原生 UVM/VCS 等价。

Stage 09 独立 replay audit 通过，288/288 个 RTL testcase PASS，证据目录的 1,443 个文件均通过 SHA-256 ledger 校验。最新 full-simulation preflight 记录为 `BLOCKED_BEFORE_FULL_SIMULATION`：4,507 个 legacy identities 已全部进入 bridge 审计，其中 341 个是 exact source-definition match，2,074 个是 range-order candidate，16 个是单候选 cross candidate，2,064 个仍是非唯一 cross/instance candidate；这些候选均不产生 coverage credit。新增 sample-site audit 已证明 7 个 AON covergroup 的 capture protocol、字段、same-sample cross 和 count-event trace 结构完整，但 228 个 shared/non-AON definitions 仍无 adapter 映射。四个短 UVM_HIGH 运行覆盖 wakeup、bark、bite 三类主 count-event group；事件顺序、5 ns 间隔和最后一个 count 与 expiry 同边沿均通过审计。该结果是局部 cadence shape evidence，仍不等价于 testcase-by-testcase waveform、shared-group 或完整 UVM/VCS sampling parity，因此不会解除 timing blocker。两个历史 `vectors.csv` 表头已完成 4,507 列候选语义分类，但仍是 diagnostic only。学校服务器上的 native VCS 数组边界探针完成 636/636 个可表示 cases，4 个越界值明确拒绝且无截断；它验证了 Python 与 VCS 的数组区间边界一致性，不验证完整 RTL/UVM sample timing。exact vector matrix 不可用，Stage 07 paper scheduler 未允许，完整 timing equivalence 仍未证明。本轮没有启动 full 仿真；blocker 从 6 项降为 5 项。

机器可读审查记录及其 SHA-256 sidecar：[review.json](../evidence/stage10_final_review/2026-11-14-v1/review.json)、[review.json.sha256](../evidence/stage10_final_review/2026-11-14-v1/review.json.sha256)。Stage 09 的逐次运行结果见[汇总](../evidence/stage09_comparison/2026-11-14-v1/summary.json)与[对照表](../evidence/stage09_comparison/2026-11-14-v1/comparison.csv)。局部 UVM/VCS 事件证据见[timing audit](../evidence/stage10_uvm_vcs_timing/2026-11-16-v1/audit.json)、[provenance](../evidence/stage10_uvm_vcs_timing/2026-11-16-v1/provenance.json)和[SHA-256 sidecar](../evidence/stage10_uvm_vcs_timing/2026-11-16-v1/audit.json.sha256)。

映射诊断入口为 `tools/audit_canonical_identity_candidates.py`。它报告 canonical labels 对 frozen source-definition 的初步 exact/range candidate 关系，不创建新的 coverage credit。新的完整 bridge 审计入口为 `tools/audit_source_identity_bridge.py`，会修复 sized-hex value range、数组 ordinal、压缩 cross、wildcard 和旧 catalog interrupt cross 结构的解析，并逐 identity 输出候选集合。运行命令：

```bash
python3 tools/audit_source_identity_bridge.py \
  --output evidence/stage10_identity_bridge/2026-11-16-v1/bridge.json
```

该审计报告和 SHA-256 sidecar：[bridge.json](../evidence/stage10_identity_bridge/2026-11-16-v1/bridge.json)、[sidecar](../evidence/stage10_identity_bridge/2026-11-16-v1/bridge.json.sha256)。它证明候选分类覆盖了完整 4,507 identity universe，但没有把非唯一候选提升为 legacy identity mapping。

2026-11-15 候选审计将 4,507 个 canonical labels 分类为：341 个直接类型标签匹配、2 个精确值区间候选、2,074 个组合值区间候选、2,080 个 cross/展开标签未决，以及 10 个其他值标签未决。精确/组合区间仍有 legacy occurrence index 未决；标签匹配也不证明 sample-site 或 UVM/VCS 采样等价。该审计授予 0 个 coverage credit，不把未知项推断为 miss，因此 175 个正向 identity、4,332 个 unknown 和 `full_coverage_rate_percent: null` 均保持不变。报告和 SHA-256 sidecar：[identity-candidates.json](../evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json)、[identity-candidates.json.sha256](../evidence/stage10_final_review/2026-11-15-v1/identity-candidates.json.sha256)。

此前一轮在 WSL Ubuntu 24.04 的项目虚拟环境中完成 105/105 全仓单测。仿真工具链保持 Verilator 5.020、Cocotb 1.9.2、lowRISC FuseSoC 0.5.dev0、Edalize 0.4.0；新增 HTML 审计依赖另记在 `configs/stage10-requirements.txt`。full coverage 门禁继续保持 blocked。

### Source-definition 分类 v2 与 full 仿真前预检（2026-11-16）

分类器 v2 将四组数组字段接到 160 项 VCS 参考区间目录，按单条样本中的值计算 source-definition reference match，并将 legacy identity 仅作为参考字段记录。对 Stage 09 的 288 份 PASS traces、16,515 个 samples 重放后，观察到 209 个不同源码定义（195 variable、14 cross），包含 42,480 次数组参考区间匹配、247 次完整 interrupt-cross 标签匹配、64,340 次 named/singleton exact match、2,908 次 count-event value-range match 和 1,454 次 count-event cross member match。另有 16,940 个数组字段观察落在参考分区之外/无可匹配 bin，保留 unresolved；unknown 不作为 miss。Pin sample 的稳定 `values[...]` bin 与 transition bin 分别识别，illegal interrupt-test cross 会被排除。

报告仍不代表原生 Verilator covergroup 或 UVM/VCS 命中；canonical coverage credit 增量为 0，175/4,507 个既有 positive identities 和 4,332 个 unknown 均未改变，full coverage rate 仍为 `null`。分类结果与 SHA-256 sidecar：[classification.json](../evidence/stage10_source_definition_classification/2026-11-16-v2/classification.json)、[sidecar](../evidence/stage10_source_definition_classification/2026-11-16-v2/classification.json.sha256)。

新增预检检查定义目录、数组参考与 640 个 Python/source boundary probes、636 个 native VCS/Python boundary probes、Stage 09 audit、分类 hash、bridge audit hash、legacy vector header audit 和 sample-site audit hash；AON capture protocol 检查通过。启动 full 仿真的前置项仍未完成：4,507-bin exact Stage 06 matrix 缺失；legacy bridge 仍有非唯一 candidate，只有 341/4,507 可以直接按源码标签匹配；228 个 shared/non-AON identities 没有 AON adapter sample API；count-event 只完成局部 UVM/VCS cadence shape 对照，完整 testcase/sample timing parity 仍未建立；Stage 07 paper scheduler 未启用。预检明确记录 `full_simulation_started: false`、`full_simulation_start_gate: BLOCKED`，没有执行仿真：[sample-site audit](../evidence/stage10_sample_site_audit/2026-11-16-v2/sample-site-audit.json)、[vector header audit](../evidence/stage10_legacy_vector_header_bridge/2026-11-16-v1/audit.json)、[VCS array boundary audit](../evidence/stage10_vcs_array_boundary/2026-11-16-v1/audit.json)、[UVM/VCS timing shape audit](../evidence/stage10_uvm_vcs_timing/2026-11-16-v1/audit.json)、[preflight.json](../evidence/stage10_full_simulation_preflight/2026-11-16-v3/preflight.json)、[sidecar](../evidence/stage10_full_simulation_preflight/2026-11-16-v3/preflight.json.sha256)。

在 WSL Ubuntu 项目虚拟环境 `build/stage10-python-env` 中，全仓单测 143/143 通过；Stage 09 replay audit 仍为 288/288 PASS。复核命令：

```bash
python3 tools/classify_source_definitions.py \
  --trace-root evidence/stage09_comparison/2026-11-14-v1 \
  --expected-trace-count 288 \
  --output evidence/stage10_source_definition_classification/2026-11-16-v2/classification.json
python3 tools/stage10_full_simulation_preflight.py
python3 tools/audit_source_identity_bridge.py \
  --output evidence/stage10_identity_bridge/2026-11-16-v1/bridge.json
python3 -m unittest discover -s tests -q
python3 tools/audit_stage09_comparison.py \
  --evidence-dir evidence/stage09_comparison/2026-11-14-v1
```

本机原论文仓库 Stage 06 转换器（旧仓库 commit `ff59c4a`，SHA-256 `31d9cf6e3c298409436be2888098ff7a9d888cd09b070bd27f0c3ddc12009506`）显示，legacy identity 最后一段由压缩 URG 行的 `offset` 产生，之后 CSV 列按 `bin_keys` 排序；`bin_manifest.json` 只登记最终列和计数，没有保存每列的展开 bin 名。该 manifest SHA-256 为 `cbc7e64a0004f0387f16f36e24edc2442a8225b3179fae6c673fe3ac84c28e3e`，其中登记的 CSV SHA-256 为 `71c02be6b80cb63973eeb96b26340f7e1d1ae2246674d148774c39c616ff1e94`。前一轮本机查找未找到对应 HTML，本轮已从学校服务器恢复。2,076 个 auto/value-range identities 的顺序候选保留为历史诊断，不允许直接提升为映射。其输入哈希见 [ordinal-range-candidates.json](../evidence/stage10_final_review/2026-11-15-v2/ordinal-range-candidates.json) 及其 [SHA-256 sidecar](../evidence/stage10_final_review/2026-11-15-v2/ordinal-range-candidates.json.sha256)。

已从服务器 `stage06_conversion_20261101T_v10` 恢复 `original_g0/g1/g10/g20/g30` 的 80 份 `grp*.html`，逐文件核验服务器 SHA-256。VCS compiler/runtime 为 `P-2019.06-SP1_Full64`，URG 为 `P-2019.06-SP1`。首份报告能准确重建 4,507 个冻结列；对另外四份报告，旧转换器的按位置对齐分别出现 126、114、83、236 处可确认的语义冲突，合计 559 处（不是 559 个去重 bin）。例如首份报告的 `wdog_regwen_cp` 行序为值 1、值 0，`original_g1` 为值 0、值 1；旧逻辑仍按原位置写入，造成两列互换。即便 bin 总数和总命中数相同，也不能证明逐列身份一致。

新增审计器 `tools/audit_legacy_urg_layouts.py` 按明确 bin 名或 singleton 值对齐，可在每份对照报告中匹配 345 个明确变量 identity，拒绝压缩区间、wildcard cross、重复名字及缺失身份；这不是采样等价或完整映射。压缩行仍不暴露逐 bin 次序，因此 v2 顺序候选继续不获 credit。可公开重放的标签布局、来源哈希、恢复记录和错误反例见 [新证据目录](../evidence/stage10_legacy_urg_layout/2026-11-15-v1/README.md)。本轮没有启动 VCS 或 RTL 仿真，没有导出历史 hit counts；Stage 09 的 175 个正向观察来源于本仓库 Cocotb traces，结果不因此增加。

### Source-definition 分类（2026-11-16）

新增 `tools/classify_source_definitions.py` 和单测，以固定 catalog 的 `definition_id` 分类 Stage 09 的 288 份 PASS trace。工具先校验相邻 `attempt.json` 的 PASS 状态、run ID、testcase、sample count 和 raw trace SHA-256，再对样本做分类。机器可读报告和 SHA-256 sidecar：[classification.json](../evidence/stage10_source_definition_classification/2026-11-16-v1/classification.json)、[classification.json.sha256](../evidence/stage10_source_definition_classification/2026-11-16-v1/classification.json.sha256)。

16,515 个样本中，观察到 43 个不同 source definitions（35 个变量定义、8 个 cross 定义）；分类记录含 64,299 次 named/singleton exact match、2,908 次 auto-bin value-range match、1,454 次 same-sample count-event cross match。11,215 个 timer config 样本仍有一个或多个数组分区未解析，共 42,480 个数组分区观察；206 个 interrupt cross 观察因导入定义结构不可靠而保持 unresolved。统计是 source-definition 层的观察，不是 legacy VCS bin 的覆盖命中；不使用旧 CSV occurrence offset，不推断 miss，也不增加原有 175 个 canonical positive identity。full coverage rate 继续为 `null`。

在 WSL 仓库根目录重放分类：

```bash
python3 tools/classify_source_definitions.py \
  --trace-root evidence/stage09_comparison/2026-11-14-v1 \
  --expected-trace-count 288 \
  --output build/stage10-source-definition-classification.json
```

此流程只消费已保存的 PASS traces，没有启动新的 RTL 仿真。source definition mapping 与 legacy VCS identity mapping、VCS/URG/Cocotb 采样等价是三类不同证据。

后续还需补齐 timer_cfg array 的逐 bin source range、shared DV/TL sample-site 和 interrupt cross 的可靠 schema 对照，并获得 UVM/VCS sample timing 对照。旧 39-run CSV 的 occurrence 顺序候选继续不获 credit，不能拿其按列结果当作新 classifier 的真值。

## 复核命令

在 WSL Ubuntu 仓库根目录运行：

```bash
python3 tools/audit_stage09_comparison.py \
  --evidence-dir evidence/stage09_comparison/2026-11-14-v1

python3 -m unittest discover -s tests -q

python3 tools/classify_source_definitions.py \
  --trace-root evidence/stage09_comparison/2026-11-14-v1 \
  --expected-trace-count 288 \
  --output build/stage10-source-definition-classification.json

# 从公开的定义标签布局重放；不需要访问学校服务器或安装 HTML parser
python3 tools/audit_legacy_urg_layouts.py \
  --layouts evidence/stage10_legacy_urg_layout/2026-11-15-v1/layouts.json \
  --output-dir build/stage10-legacy-urg-replay
```

该审计重放现存 Stage 09 XML、trace、向量、选择决策与 hashes；它不是新的 UVM/VCS 仿真，也不补全 bin/sample 映射。当前 full coverage rate 保持 `null / not reportable`，直到完整身份映射、采样点语义、exact vectors 和 VCS/UVM sampling comparison 有证据支持。
