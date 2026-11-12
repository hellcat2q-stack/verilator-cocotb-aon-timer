# 工具目录

按阶段增加固定源码校验、FuseSoC/Verilator build、seeded Cocotb runner、coverage JSON、bin-by-run 转换和审计脚本。每个入口登记参数、输出格式、工具版本与验收方式。

阶段 04 使用 `test_sequences.py` 和 `run_stage04_tests.sh`；runner 在独立的 pinned OpenTitan source tree 上构建，接受 `SOURCE_ROOT`、`PYTHON_ENV`、`WORK_ROOT`、`RANDOM_SEED` 和 `RUN_ID`，保存 `run_manifest.json`、Cocotb XML summary 与完整工作日志到 `WORK_ROOT`。

阶段 05 使用 `stage05_corpus.py` 校验 pool/freeze、`run_stage05_corpus.py` 顺序执行冻结 seed 并保留每个 attempt。Cocotb testcase 从 `AON_TIMER_TEST_POOL` 读取冻结参数；默认读取 `configs/stage05-test-pool.json`。默认正式结果写入所给 `WORK_ROOT`，不覆盖已有 run 目录。
