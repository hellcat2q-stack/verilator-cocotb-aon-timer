# 独立的参考采样修复版本

本目录建立 `pinned-sampling-fixes-v1`，基于固定 OpenTitan revision，只修复三处参考 scoreboard 逻辑。原始固定版、既有 adapter 和历史证据不变；RTL、刺激、seed、时钟和已有实验预算不变。

| 文件 | 作用 |
| --- | --- |
| `instrument.py` | 先调用冻结的 `stage10_sample_parity/instrument.py`，再应用三个经过差异审阅的参考修复，导出完整 patch 和仅修复 patch |
| `event_wait_probe.sv` | 独立测量 `@(event.triggered)` 和 `@(event)` 对五次触发的实际接收数 |
| `fork_cleanup_probe.sv` | 独立测量原 fork 拓扑与隔离 child 拓扑在复位后的线程残留 |
| `run_cocotb.sh` | 独立构建、三组真实 RTL 回放与 runtime hashes；继承冻结 runner 的总线与时钟协议 |
| `collect_run.py` | 收集本次 build/run、输入、原始日志哈希、实际 compiler/runtime 版本、两个原生探针和 variant 身份 |
| `audit.py` | 验证 source/tool/XML hashes、明确的三个修复、两个原生探针、producer 唯一性及逐组逐时刻样本相等性 |

新 adapter 在 `tools/pinned_sampling_fixed_adapter.py`，测试入口为 `tools/test_uvm_sample_fix_replay.py`。入口复用原有总线/时钟回放函数，只在独立进程内选择新 adapter；原回放代码的文件内容没有改动。新 trace 使用 `aon_timer_pinned_sampling_fix_trace_v1`，不允许导入现有 canonical 矩阵。

在新服务器 `$RUN_ROOT/inputs/` 中放入本目录 `instrument.py`、两个探针和 `configs/stage10-sample-fix-v1.json`；同时复制冻结目录的 `run_vcs.sh`、`collect_vcs.py`、`verify_source.py`、`aon_timer_smoke_vseq.sv` 及原短测协议。将冻结的 `instrument.py` 复制成 `instrument_base.py`，不要覆盖原文件。然后在参考项目兼容环境中运行：

```bash
bash "$RUN_ROOT/inputs/run_vcs.sh" "$REFERENCE_ROOT" "$RUN_ROOT"
python3 "$RUN_ROOT/inputs/collect_vcs.py" --run-root "$RUN_ROOT"
python3 "$RUN_ROOT/inputs/verify_source.py" --run-root "$RUN_ROOT"
```

两个探针各在新的独立子目录编译运行，例如：

```bash
mkdir "$RUN_ROOT/event-probe"
cd "$RUN_ROOT/event-probe"
vcs -full64 -sverilog ../inputs/event_wait_probe.sv -o simv > build.private.log 2>&1
printf '%s\n' "$?" > build.exit
timeout 30 ./simv > simulation.private.log 2>&1
printf '%s\n' "$?" > process.exit
```

fork 探针以同样方式放在 `fork-probe/`，源文件换为 `fork_cleanup_probe.sv`。运行过程必须像 AON runner 一样保留退出码，失败不覆盖或删除；`collect_run.py` 会验证并导出探针结果。采集前把 runner 原退出码写入 `runner.exit`，不要根据是否存在输出文件猜测 PASS。

```bash
python3 tools/stage10_sample_fix/collect_run.py --run-root "$RUN_ROOT"
```

取回 `public/` 后，在 WSL 本仓库根目录执行：

```bash
SOURCE_ROOT=/path/to/clean-pinned-opentitan \
PYTHON_ENV=/path/to/compatible-venv \
WORK_ROOT=/path/to/new-linux-run \
bash tools/stage10_sample_fix/run_cocotb.sh /path/to/public

python3 tools/stage10_sample_parity/export_cocotb.py \
  --run-root /path/to/new-linux-run --output-dir /path/to/public

python3 -m tools.stage10_sample_fix.audit \
  --evidence-dir /path/to/public --output /path/to/public/audit.json
```

审计要求三组均 PASS、总线和响应完全对齐、RTL 逐 AON 边沿一致、producer 不重复、每个 group 的样本值/顺序/时刻一致，并校验同时间多重集合。不同 covergroup 的同时间调度顺序单独报告，不伪称完全一致。通过只表示三个短测与声明修复版一致，不代表原版等价或完整矩阵通过；full 门禁仍由 `tools/stage10_full_simulation_preflight.py` 管理。
