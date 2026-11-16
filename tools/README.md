# 工具目录

## 2026-11-14 新增：实际 Stage 08 pilot

- `run_stage08_pilot.py --source-root <clean-pinned-source> --python-env <compatible-venv> --work-root <new-linux-work> --output <new-evidence-dir>`：读 `configs/stage08-pilot.json` 冻结协议，单实验内复用编译，执行 4 warmup + 8 testcase UCB 的真实仿真，导出正向 vectors、XML/trace、反馈事件链与观察曲线。超时/失败消耗预算，未观察 identity 保持 unknown。
- `audit_stage08_pilot.py --evidence-dir <pilot-dir> --output <separate-audit.json>`：校验输入与证据哈希，从真实 XML/trace 重算结果、novelty、奖励和 UCB 选择。该回放不是额外 RTL 运行，也不是 UVM/VCS parity。
- `stage08_preflight.py` 现明确检查完整 4,507-bin 论文口径，不评价 pilot readiness；移除“必须原生 SV covergroup”的措辞。完整映射/采样等价性仍待补。
- `audit_conditional_reset.py` v2 增加真实 revision、clean checkout、四个 pinned 源码哈希和两个 guard 验证；`configs/conditional-reset-audit.json` 已在正确源码重做。下文旧登记中的“Verilator 等价”应理解为 live Python/Cocotb 功能覆盖等价性，并不要求原生 SV covergroup。

工具测试：`python3 -m unittest discover -s tests -q`。最终 RTL 证据及复现命令见 [阶段 08](../08_在线覆盖闭环/README.md)。

## 2026-11-14 新增：Stage 09 工程对照

- `stage09_protocol.py` 校验 VCS 参考数组分区并生成 12 个配置/功能动作、冻结 pool/protocol/freeze 和确定性的 UCB、Random、round-robin Full、`ucb_no_reward` 选择策略。
- `test_stage09_sequences.py` 提供 8 个配置块和零值/最大值动作；每步写 CSR、读回 RTL 配置，并保存同一 trace sample 的 checkpoint。
- `run_stage09_comparison.py` 检查 pinned clean source 与 OpenTitan 兼容工具链，单独预编译一次，交错运行 288 个单 testcase RTL attempts，保存 XML、trace、positive-only vector、选择/结果哈希链和策略汇总。失败消耗预算且不获覆盖奖励。
- `audit_stage09_comparison.py` 从 XML、trace fields 和 checkpoint 独立重放结果、数组/显式 identity 分类、novelty reward、策略选择、汇总和文件 hash ledger；unknown 保持 unknown。
- 实测结果和限制见 [阶段 09](../09_基线对照与消融/README.md) 与 [Stage 09 evidence](../evidence/stage09_comparison/2026-11-14-v1/summary.json)。策略定义是工程对照，不是论文 cluster UCB、论文 Full 或 VCS/UVM parity。

在 WSL Ubuntu 中，使用新的 Linux work 目录和 evidence 目录运行 `run_stage09_comparison.py`，完成后运行 `audit_stage09_comparison.py --evidence-dir <run-dir>`。`tests/test_stage09_comparison.py` 覆盖 160 个参考数组 bins、策略回放确定性、freeze tamper 和空 trace 拒绝。

## 2026-11-15 新增：canonical identity 候选映射诊断

audit_canonical_identity_candidates.py --output <new-report.json> 按冻结的 canonical labels 和 pinned type-definition catalog 分类直接身份匹配、value-range 候选与 unresolved cross/instance 标签。Range 候选不获 coverage credit，也不改变 Stage 08/10 readiness gate；输出记录两个输入文件的 SHA-256。tests/test_canonical_identity_candidates.py 检查 instance index、range partition 与 cross 不猜测。

该审计还输出 ordinal range candidates：仅当 canonical occurrence 数与连续且唯一的源 value-range 数相等、offset 为 `0..N-1` 时，按值域顺序生成一对一候选。候选仍需原始 URG bin 行顺序或等价 VCS 证据确认；这一步不会生成完整向量或增加 coverage credit。若要把旧 Stage 06 header 绑定到证据，可同时传入 `--legacy-manifest`、`--legacy-matrix` 和 `--legacy-converter`；工具验证 manifest 声明的 CSV hash 和完整 header 次序，并在报告中记录三个输入的 SHA-256，不保存本机路径。

## 2026-11-16 新增：source-definition v2 与 full 仿真前门禁

- `classify_source_definitions.py` 将固定的 160 个 VCS 参考数组分区映射到单条 trace sample，解析完整 interrupt-cross bin label，并将 interrupt pin value/transition bins 分开分类。数组和 cross 结果只属于 source-definition/reference match，不增加旧 canonical coverage credit；illegal `intr_test=1 && intr_state=0` cross 会排除。
- `stage10_full_simulation_preflight.py` 校验 catalog、数组来源/Python 边界审计、Stage 09 replay audit、source-classification hashes、identity bridge、Stage 06 exact matrix 和 sample-site readiness，写出只读的 preflight JSON。工具不会启动仿真；只有所有显式必需检查都为 true 且 blocker 为空时才会报告 `READY`。它还要求 Stage 08 明确验证 Verilator 对 160 个源数组 bins 的等价性。
- 预检会验证 `stage10_sample_matrix` 八用例审计的 sidecar 并从原始采样证据重放，报告 8/8 有界修复版短测结果；该诊断不放宽完整 parity、bin identity、shared-scope 或 Stage 06/07 的门槛。最新结果见 `evidence/stage10_full_simulation_preflight/2026-11-16-v10/preflight.json`，当前仍为 blocked。默认输出使用新的 v10 目录，不覆盖旧预检。
- 重放：`python3 tools/classify_source_definitions.py --trace-root evidence/stage09_comparison/2026-11-14-v1 --expected-trace-count 288 --output evidence/stage10_source_definition_classification/2026-11-16-v2/classification.json`，然后运行 `python3 tools/stage10_full_simulation_preflight.py`。分类报告和预检报告均生成 SHA-256 sidecar。

## 2026-11-16 新增：历史 vector header 与 native VCS 数组边界审计

- `audit_legacy_vector_headers.py` 只读取两个历史 `vectors.csv` 的表头，将 4,507 个列名分类为 exact semantic、range、array-range 和 cross candidate。它不读取 hit-count 行，不导入历史命中数，所有 candidate 的 `coverage_credit_granted` 固定为 0，`promotion_allowed` 固定为 false。
- `vcs_array_boundary_probe.py` / `run_vcs_array_boundary_probe.py` 在学校服务器的 VCS `P-2019.06-SP1` 上运行独立的 636-case timer_cfg array boundary probe，并记录 4 个越界拒绝。`audit.json` 逐项比较 Python reference interval 与 native VCS bin interval；该审计只覆盖数组边界，不证明 UVM/VCS 与 Cocotb 的 sample timing parity。
- 当前证据：`evidence/stage10_legacy_vector_header_bridge/2026-11-16-v1/`、`evidence/stage10_vcs_array_boundary/2026-11-16-v1/`。`stage10_full_simulation_preflight.py` 会校验两类 sidecar；v10 输出 6 个具体阻塞条件和一条未通过检查列表，full gate 为 `BLOCKED`。

## 2026-11-16 新增：完整 legacy identity bridge 审计

- `audit_source_identity_bridge.py` 对冻结的 4,507 个 canonical identities 与 pinned 4,507 条 source definitions 做完整候选审计。变量项支持 `name:`、singleton、sized-hex/decimal `values:{[...]}`、source `auto[...]` 和连续 range-order candidate；cross 项支持 source member 解析、wildcard、压缩 range、instance index，并对旧 catalog 中 interrupt cross 的错误分割使用 `bin_name` 回退解析。
- 报告中的 `EXACT_SOURCE_DEFINITION`、`RANGE_ORDER_CANDIDATE` 和 `CROSS_*_CANDIDATE` 都是身份候选，`coverage_credit_granted` 固定为 0；非唯一候选不能用于推断命中或 miss。当前 pinned 结果为 341 exact、2,074 range-order candidate、16 单候选 cross、2,064 非唯一 cross candidate。
- 运行：`python3 tools/audit_source_identity_bridge.py --output evidence/stage10_identity_bridge/2026-11-16-v1/bridge.json`。`stage10_full_simulation_preflight.py` 会校验该报告及其 sidecar/tool hash，但仍要求独立 URG/VCS expansion/order 证据后才能解除 full 仿真门禁。

## 2026-11-16 新增：AON sample-site / shared-scope 审计

- `audit_sample_site_mapping.py` 读取 `configs/coverage_schema.json`，递归审计公开 raw traces 的 7 个 AON covergroup：字段键、同次采样 cross、事件名、trace sample counts、interrupt-test illegal 条件，以及三个 count-event group 的 RTL counter/cadence 元数据。它同时登记 228 个 shared/non-AON definitions 的未接入范围，并固定 `coverage_credit_granted=0`、`unknowns_are_misses=false`。
- 运行：`python3 tools/audit_sample_site_mapping.py`，结果写入 `evidence/stage10_sample_site_audit/2026-11-16-v1/` 并生成 SHA-256 sidecar。报告可以把 AON capture protocol 标为 complete，但不会把 shared scope 或 count-event UVM/VCS timing parity 误报为 complete。
- `stage10_full_simulation_preflight.py` 现在校验该审计的 sidecar 和工具 hash，并将 blocker 拆为 AON capture protocol、shared/non-AON scope、count-event timing parity 三类。full gate 仍必须保持 BLOCKED，直到 exact identity/vector 和独立 parity 证据齐全。

## 2026-11-16 新增：UVM/VCS count-event timing shape 对照

- `audit_uvm_vcs_timing.py` v2 实际调用 `TimerSampleScheduler.tick()`，以 UVM_HIGH 的 count 数为假定 countdown 长度，从首个 count 对齐比较控制事件顺序。wakeup 相邻 count 间隔为 5 μs；bark/bite 各只有一个主 count，不能测量间隔。伴随事件不用于补足三个主 group 的验证。
- 四个短运行保留 21 条事件。工具核验来源 JSON、原日志 hash、事件摘要 hash、工具和模型 hash，拒绝重复 expiry、事件倒序、不等间隔和被修改的摘要。`count_event_shape_comparison_complete` 可以为 true；完整 `independent_uvm_vcs_timing_comparison_complete` 固定为 false。工具不读取 VDB 或历史 hit counts，不授予 coverage credit。
- 这些消息记录事件触发处，没有记录 covergroup 实际调用或实参。当前 build tree 的 scoreboard 还与 pinned revision 不同，simv 完整 build 来源未重建，因此只作诊断。四周期 startup 延迟、实际采样调用次数、逐样本取值和完整 waveform parity 均未验证。

重放命令：

```bash
python3 tools/audit_uvm_vcs_timing.py \
  --evidence-dir evidence/stage10_uvm_vcs_timing/2026-11-16-v2 \
  --output build/stage10-uvm-control-shape-replay.json
```

证据说明见 [v2 README](../evidence/stage10_uvm_vcs_timing/2026-11-16-v2/README.md)。下一轮应在独立 pinned build 的实际 `.sample()` 分支记录全部实参，与相同显式刺激下的 Cocotb 短运行逐条比较；具体要求见 [逐采样对照计划](../configs/stage10-uvm-sample-parity-plan.json)。full gate 保持 BLOCKED。

## 原有阶段工具

`audit_legacy_urg_layouts.py` 恢复 URG `grp*.html` 的定义标签布局，验证首份报告与冻结 4,507 列一致，并检测不同报告的按位置对齐冲突。明确变量按 bin 名或 singleton 值匹配；压缩行和通配 cross 不猜测。HTML 导入依赖 `configs/stage10-requirements.txt`；使用 `--layouts <layouts.json>` 重放时仅需 Python 标准库。`tests/test_legacy_urg_layouts.py` 覆盖行序互换、singleton 包装、重复/压缩身份拒绝、公开布局重放和导出内容范围。证据见 `evidence/stage10_legacy_urg_layout/2026-11-15-v1/`。

按阶段增加固定源码校验、FuseSoC/Verilator build、seeded Cocotb runner、coverage JSON、bin-by-run 转换和审计脚本。每个入口登记参数、输出格式、工具版本与验收方式。

阶段 04 使用 `test_sequences.py` 和 `run_stage04_tests.sh`；runner 在独立的 pinned OpenTitan source tree 上构建，接受 `SOURCE_ROOT`、`PYTHON_ENV`、`WORK_ROOT`、`RANDOM_SEED` 和 `RUN_ID`，保存 `run_manifest.json`、Cocotb XML summary 与完整工作日志到 `WORK_ROOT`。

阶段 05 使用 `stage05_corpus.py` 校验 pool/freeze、`run_stage05_corpus.py` 顺序执行冻结 seed 并保留每个 attempt。Cocotb testcase 从 `AON_TIMER_TEST_POOL` 读取冻结参数；默认读取 `configs/stage05-test-pool.json`。默认正式结果写入所给 `WORK_ROOT`，不覆盖已有 run 目录。

阶段 06 使用 `stage06_matrix.py --corpus-manifest ... --vector-dir ... --out-dir ...` 输出 bin-by-run CSV 和 audit JSON。矩阵保持 4,507 canonical identities，cells 为 `1`/`0`/`?`；failed run 全部 mask 成 unknown，不获得覆盖奖励。

阶段 07 使用 `PYTHONHASHSEED=0 python3 tools/stage07_clustering.py --bin-ids references/canonical_bin_ids.txt --output-dir evidence/stage07_partial --max-cluster-size 256 --seed 0` 生成稳定 bin-to-cluster mapping 与回放审计。partial hits 不能确定 misses 或剩余未覆盖集合，coverage scores/UCB inputs 继续 blocked。

`tools/import_bin_definitions.py --manifest <coverage_manifest.v1.json>` 校验并导出 revision-matched bin definitions，不复制历史命中数。`tools/import_array_bin_ranges.py --vectors <vectors.csv> --protocol <protocol.json> --mapping-validation <mapping_validation.json>` 只读取 VCS vectors CSV 的首行表头，导出 160 个 timer_cfg 数组 bin 的参考区间与 SHA-256 sidecar；不会读取运行数据行或导入 hit counts。`tools/stage08_preflight.py` 汇总定义目录、数组边界参考、Stage 06 矩阵、Stage 07 scheduler gate 与 `configs/coverage_schema.json` 中的 sample-site mapping 到 `evidence/stage08_preflight/`；其 readiness 输出使用 v2 schema，只做门禁审计，不执行调度或仿真，并明确将 Verilator 区间等价性保留为 blocker。

`tools/audit_conditional_reset.py --source-root <pinned-opentitan>/src --source-revision <revision> --output configs/conditional-reset-audit.json` 检查 AON Timer/CIP DV 源码中的 `num_edn` 声明、覆盖赋值和 `resets_cg` 条件保护。只有确认没有配置覆盖时才输出 `NOT_APPLICABLE_NUM_EDN_ZERO`；该工具不把静态审计当成运行时 VCS/UVM 证据。

`tools/audit_array_bin_partition.py --source-file <aon_timer_env_cov.sv> --range-catalog references/array_bin_ranges.v1.json --output evidence/stage03_array_bin_partition_audit.json` 重新计算源码声明的均匀数组分区，并对 Python/Cocotb 分类器逐 bin 做上下界探针；它明确保留 native Verilator/SystemVerilog coverage 未验证限制。

`tools/audit_array_bin_observations.py --output <audit.json>` 校验 Stage 05 raw trace hashes 与样本元数据，再将 `timer_cfg_cg` 原始数值按 VCS 参考区间分类。它只导出正向观察 audit，不生成 coverage vector，不对未观察 bins 推断 miss，也不宣称 Verilator coverage parity。

count-event trace v2 为固定 wrapper 增加只读 counter 观察口；`TimerSampleScheduler` 模拟 scoreboard 的 4 个 AON startup clocks、countdown 更新与 expiry sampling，runner 复核每条 count group 的 event shape 和 RTL counter 值。连续 expiry 后还会重入 startup 等待。该模型尚未完成与独立 VCS/UVM 实际采样调用及实参的比对，因此其时序属于实现验证状态，不代表 coverage parity；Stage 06 继续只转换 source-confirmed explicit named bins。

阶段 04 runner 通过 `tools/cocotb_coverage_adapter.py` 在可观测的 TL CSR write/read、AON pin 变化及三个计数器 covergroup 上追加 raw trace JSON。计数器事件按 pinned scoreboard 的 4 周期启动延迟、倒计时长度和到期额外采样建模，计数值由仿真顶层只读输出观察；尚未与 UVM/VCS 仿真逐事件比对，所以不宣称时序等价。文件由 testcase `finally` 路径保存并在 run manifest 中记录哈希。trace schema v2 与旧版 v1 并存，阶段 05 runner 复核每个 trace 的 hash、样本总数、covergroup 分布和元数据。`tools/raw_trace_to_vectors.py` 只把 source-confirmed named explicit-bin hits 转成 `PARTIAL_VALIDATED` sparse vectors，不推断 miss；auto-bin/cross partition、条件 reset 适用性和共享 228 identities 仍未解决。

## 2026-11-16 新增：八用例固定参考短矩阵

`stage10_sample_matrix/` 将已修复的 pinned UVM 参考测试扩展到八组确定性短测，包含 `INTR_TEST`、prescale、运行中更新/重启、复位重启和 watchdog sleep/pause。它独立记录 VCS 实际 `.sample()` 参数和复位/sleep 时序，再由干净 pinned RTL 的 Cocotb runner 回放。结果必须经过 source、工具、XML、TL、RTL 边沿、逐组元组及 producer 去重审计；所有结果保持 0 个 coverage credit。该八用例矩阵仍不等于完整采样 parity，也不解除 full 仿真门禁。运行方式见 [`stage10_sample_matrix/README.md`](stage10_sample_matrix/README.md)。

## 2026-11-17 复跑记录

Stage 09 工程矩阵的复跑与独立审计输出至 `evidence/stage09_comparison/2026-11-16-v2/`；source-definition 分类和 sample-site audit 输出至各自 `2026-11-17-v1/` 目录。重放最新 full 仿真门禁：

```bash
build/stage10-python-env/bin/python3 tools/stage10_full_simulation_preflight.py \
  --trace-root evidence/stage09_comparison/2026-11-16-v2 \
  --replay-audit evidence/stage09_comparison/2026-11-16-v2/replay-audit.json \
  --classification evidence/stage10_source_definition_classification/2026-11-17-v1/classification.json \
  --sample-site-audit evidence/stage10_sample_site_audit/2026-11-17-v1/sample-site-audit.json \
  --output evidence/stage10_full_simulation_preflight/2026-11-17-v2/preflight.json
```

当前输出仍为 `BLOCKED_BEFORE_FULL_SIMULATION`；此工具只核对启动条件，不启动 full run。
