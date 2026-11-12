# 阶段 05：测试池与初始语料

状态：初始功能语料已按冻结协议实跑并校验 partial raw trace；不含随机 stress-all 或覆盖率向量。

## 冻结协议

- 测试池：`configs/stage05-test-pool.json`，固定 4 个阶段 04 用例及参数。
- 冻结记录：`configs/stage05-freeze.json`，包含 pool SHA-256、源码 revision 和冻结状态。
- Seed：`[1]`。场景参数是固定值，seed 只用于 Cocotb 的运行记录；不把无效的 seed sweep 当作刺激多样性。
- 预算：1 次完整 suite、1 worker、每次最多 300 秒；suite 仿真时间上限 25,000 ns。
- 失败处理：每次 attempt 单独保留 run manifest、`results.xml`、日志和 hash；继续运行尚未执行的冻结 seed。

## 运行与产物

在 WSL 中使用固定 OpenTitan revision 的 Linux worktree 和阶段 02 Python 环境：

```bash
python3 tools/run_stage05_corpus.py \
  --source-root /path/to/pinned/opentitan \
  --python-env /path/to/stage02/python-env \
  --work-root /path/to/stage05-runs --dry-run

python3 tools/run_stage05_corpus.py \
  --source-root /path/to/pinned/opentitan \
  --python-env /path/to/stage02/python-env \
  --work-root /path/to/stage05-runs
```

runner 会先校验 frozen pool hash、seed、测试顺序、预算和源码 revision；正式运行后为每个 seed 生成 attempt manifest 与汇总 `corpus_manifest.json`，并逐项校验 trace 文件 hash、sample 总数、covergroup 计数和 run/source/schema 元数据。成功运行摘要见 [`evidence/stage05_initial_corpus.json`](../evidence/stage05_initial_corpus.json)，partial raw trace 与审计摘要见 [`evidence/stage03_raw_trace/`](../evidence/stage03_raw_trace/)，执行记录见 [`实施记录.md`](实施记录.md)。

本语料是功能场景与检查结果，不是 4,507-bin coverage vector。精确 bin 分区和共享 covergroup sampling 尚未完成，不能将这些结果用于 coverage-based 调度或与 VCS 覆盖分数等同。
