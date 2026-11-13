# 工具目录

按阶段增加固定源码校验、FuseSoC/Verilator build、seeded Cocotb runner、coverage JSON、bin-by-run 转换和审计脚本。每个入口登记参数、输出格式、工具版本与验收方式。

阶段 04 使用 `test_sequences.py` 和 `run_stage04_tests.sh`；runner 在独立的 pinned OpenTitan source tree 上构建，接受 `SOURCE_ROOT`、`PYTHON_ENV`、`WORK_ROOT`、`RANDOM_SEED` 和 `RUN_ID`，保存 `run_manifest.json`、Cocotb XML summary 与完整工作日志到 `WORK_ROOT`。

阶段 05 使用 `stage05_corpus.py` 校验 pool/freeze、`run_stage05_corpus.py` 顺序执行冻结 seed 并保留每个 attempt。Cocotb testcase 从 `AON_TIMER_TEST_POOL` 读取冻结参数；默认读取 `configs/stage05-test-pool.json`。默认正式结果写入所给 `WORK_ROOT`，不覆盖已有 run 目录。

阶段 06 使用 `stage06_matrix.py --corpus-manifest ... --vector-dir ... --out-dir ...` 输出 bin-by-run CSV 和 audit JSON。矩阵保持 4,507 canonical identities，cells 为 `1`/`0`/`?`；failed run 全部 mask 成 unknown，不获得覆盖奖励。

阶段 07 使用 `PYTHONHASHSEED=0 python3 tools/stage07_clustering.py --bin-ids references/canonical_bin_ids.txt --output-dir evidence/stage07_partial --max-cluster-size 256 --seed 0` 生成稳定 bin-to-cluster mapping 与回放审计。partial hits 不能确定 misses 或剩余未覆盖集合，coverage scores/UCB inputs 继续 blocked。

`tools/import_bin_definitions.py --manifest <coverage_manifest.v1.json>` 校验并导出 revision-matched bin definitions，不复制历史命中数。`tools/import_array_bin_ranges.py --vectors <vectors.csv> --protocol <protocol.json> --mapping-validation <mapping_validation.json>` 只读取 VCS vectors CSV 的首行表头，导出 160 个 timer_cfg 数组 bin 的参考区间与 SHA-256 sidecar；不会读取运行数据行或导入 hit counts。`tools/stage08_preflight.py` 汇总定义目录、数组边界参考、Stage 06 矩阵、Stage 07 scheduler gate 与 `configs/coverage_schema.json` 中的 sample-site mapping 到 `evidence/stage08_preflight/`；其 readiness 输出使用 v2 schema，只做门禁审计，不执行调度或仿真，并明确将 Verilator 区间等价性保留为 blocker。

`tools/audit_array_bin_observations.py --output <audit.json>` 校验 Stage 05 raw trace hashes 与样本元数据，再将 `timer_cfg_cg` 原始数值按 VCS 参考区间分类。它只导出正向观察 audit，不生成 coverage vector，不对未观察 bins 推断 miss，也不宣称 Verilator coverage parity。

阶段 04 runner 通过 `tools/cocotb_coverage_adapter.py` 在可观测的 TL CSR write/read 与 AON pin 事件上追加 source-aligned raw trace JSON；文件由 testcase `finally` 路径保存并在 run manifest 中记录哈希。阶段 05 runner 复核每个 trace 文件的 hash、样本总数、covergroup 分布和 testcase/source/schema 元数据，并把摘要写入 attempt/corpus manifest。`tools/raw_trace_to_vectors.py` 只把 source-confirmed named explicit-bin hits 转成 `PARTIAL_VALIDATED` sparse vectors，不推断 miss；count-event samples、conditional reset group 和共享 228 identities 未接入。
