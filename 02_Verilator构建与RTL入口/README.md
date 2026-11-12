# 阶段 02：Verilator 构建与 RTL 入口

状态：通过。固定 revision 的 AON Timer RTL 已完成 Verilator 编译和一次 Cocotb smoke；覆盖模型迁移仍属后续阶段。

## 运行

在 WSL Ubuntu 中使用 Linux 文件系统上的 `SOURCE_ROOT` 和 `WORK_ROOT`：

```bash
export SOURCE_ROOT=/path/to/pinned/opentitan
export WORK_ROOT=/path/to/linux-filesystem/build/stage02
bash tools/setup_stage02_env.sh
RANDOM_SEED=1 bash tools/run_stage02_smoke.sh
```

Python 依赖由 `configs/stage02-requirements.txt` 单独固定。该 OpenTitan revision 的 prim generator 需要 lowRISC FuseSoC/Edalize API，因此不能直接用系统已有的 FuseSoC 2.4.5 / Edalize 0.6.3 环境。阶段脚本验证 FuseSoC `0.5.dev0`，运行默认 generic prim 实现。

## 验收

固定源码成功通过 FuseSoC setup、Verilator 5.020 编译，以及 Cocotb 1.9.2 测试 `reset_dual_clock_and_register_read_write`。测试检查双时钟复位、阈值寄存器默认值、TL-UL 写入和读回，seed 为 1，仿真时间 841 ns。摘要、哈希和限制见 [`evidence/stage02_smoke_summary.json`](../evidence/stage02_smoke_summary.json)。

此 smoke 不启用 Verilator coverage，也不等同于移植官方 UVM 测试或覆盖率模型；不能据此声称与 VCS coverage 等价。编译保留了若干 OpenTitan `SPLITVAR` / `UNOPTFLAT` lint warning，并用 `--Wno-fatal` 允许仿真继续；后续应记录并评估这些 warning。
