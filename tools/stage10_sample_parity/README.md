# 独立 UVM 实际采样与 Cocotb 回放

这组工具只运行三组确定性短测试。不会启动 full、改变已有实验预算或把旧 VCS hit counts 导入 Cocotb。

| 文件 | 用途 |
| --- | --- |
| `instrument.py` | 核验固定 scoreboard 哈希，在九处实际 `.sample()` 前插入无等待日志；另记录 TL callback、时钟和复位，固定诊断快时钟为 50 MHz |
| `aon_timer_smoke_vseq.sv` | 独立副本中的诊断序列，显式配置 wakeup/bark/bite 三种情况 |
| `run_vcs.sh` | 从固定 Git revision 导出并核验 10,514 个 blobs，创建独立 Git 元数据，编译及运行三组短测试 |
| `collect_vcs.py` | 导出实际调用、控制消息、运行退出码和日志哈希；不导出 VDB、二进制和私有路径 |
| `verify_source.py` | 构建完成后再次核验全部源码，只允许声明的四个文件差异 |
| `run_cocotb.sh` | 使用干净固定版本另建 Verilator，按 VCS 实际接受的完整 TL 地址/数据/时刻回放；adapter 使用低六位 CSR offset |
| `export_cocotb.py` | 导出原始 trace、回放记录、运行 manifest、XML；仅把 XML 的源码路径规范成仓库相对路径并保留转换前后哈希 |
| `audit.py` | 校验 runtime/tool/source/export hashes，比较 bus、逐边沿 RTL 状态、实际采样次数、元组、顺序和时刻 |

运行协议见 `configs/stage10-paired-short-v1.json`，实际 Cocotb 测试在 `tools/test_uvm_sample_replay.py`。

在已激活参考项目兼容工具环境的服务器上，将本目录的 `run_vcs.sh`、`instrument.py`、`collect_vcs.py`、`aon_timer_smoke_vseq.sv` 和协议文件复制进**新建的** `$RUN_ROOT/inputs/`，再运行：

```bash
bash "$RUN_ROOT/inputs/run_vcs.sh" "$REFERENCE_ROOT" "$RUN_ROOT"
python3 "$RUN_ROOT/inputs/collect_vcs.py" --run-root "$RUN_ROOT"
python3 tools/stage10_sample_parity/verify_source.py --run-root "$RUN_ROOT"
```

`REFERENCE_ROOT` 指原参考项目，脚本仅从其中读取固定 Git 对象。所有 source/build/results 都在新 `RUN_ROOT`。服务器旧 Git 不支持从 shallow repository fetch，故新 `.git` 的对象目录通过只读访问 alternates 引用既有对象；refs/index 不共享，旧 checkout 文件不改动。导出前后均验证源码内容，不用 Git HEAD 单独证明构建来源。完整日志、失败尝试和二进制保留在服务器。

把 `public/` 取回本地后，在 WSL 的本仓库根目录运行：

```bash
SOURCE_ROOT=/path/to/clean-pinned-opentitan \
PYTHON_ENV=/path/to/compatible-venv \
WORK_ROOT=/path/to/new-linux-run \
bash tools/stage10_sample_parity/run_cocotb.sh /path/to/public

python3 tools/stage10_sample_parity/export_cocotb.py \
  --run-root /path/to/new-linux-run --output-dir /path/to/public

python3 -m tools.stage10_sample_parity.audit \
  --evidence-dir /path/to/public --output /path/to/public/audit.json
```

审计还要求 `attempts.json`：它登记所有准备/构建尝试的原因、退出码、输入和日志哈希及真实测试状态。本轮实际尝试已存入公开证据。新一轮必须按其 schema 生成自己的记录；不能复制旧 attempt 声明新运行。对工具、source variant 或协议的任何后续改动使用新的证据目录，保留本轮结果。
