# 阶段 09：基线对照与消融

状态（2026-11-14）：**工程范围对照已实跑并通过独立 replay audit；不是论文方法复现完成。**

## 实测结果

- 固定 OpenTitan `9f20940d494a223cc950a5b98f748fb28109d458`，Verilator 5.020、Cocotb 1.9.2、lowRISC FuseSoC 0.5.dev0、Edalize 0.4.0。
- 12 个确定性动作覆盖 8 个配置块、零值/最大值端点和 smoke/jump 功能序列。每个配置块写入参数后读取 RTL 寄存器，并用 trace mirror checkpoint 复核。
- UCB、Random、Full（固定动作顺序 round-robin）和 `ucb_no_reward` 消融；选择种子 1、7、19；每策略/种子 24 次尝试；单 worker；统一固定 simulation seed 1。共 288 次真实 RTL 仿真，288/288 PASS，累计 16,515 个 raw samples。
- UCB、Full、无奖励消融在三个选择种子上均观察到 175 个正向 identity：15 个 source-named 与 160 个 VCS 参考数组分区 identity，4,332 unknown。三者的整条决策轨迹相同：奖励信息在动作池探索完成后不再改变选择，结果不能解释为 UCB 优于 Full。
- Random 在选择种子 1/7/19 下分别观察到 167/160/168 个 identity（15 source-named；152/145/153 array reference），4,340/4,347/4,339 unknown。随机策略没有保证覆盖全部动作。
- 所有策略使用相同 attempt 数、选择种子集合、worker 数和 25,000 ns/attempt 仿真时间上限；实际消耗仿真时间按策略/种子分别记录，不作墙钟效率优劣结论。预编译一次，耗时约 13.9 秒，与仿真统计分开。
- 独立 replay audit 重算了 testcase trace、正向 identity、数组分类、checkpoint、novelty reward、UCB 选择、输入哈希和结果链。288/288 条均通过；0 个 inferred misses。

证据：[汇总](../evidence/stage09_comparison/2026-11-14-v1/summary.json)、[对照 CSV](../evidence/stage09_comparison/2026-11-14-v1/comparison.csv)、[replay audit](../evidence/stage09_comparison/2026-11-14-v1/replay-audit.json)、[文件哈希](../evidence/stage09_comparison/2026-11-14-v1/sha256.txt)。每次 attempt 的选择、XML、trace 和正向 vector 保存在对应策略目录。

## 复现命令（WSL Ubuntu）

协议和动作池已冻结于 `configs/stage09/`。每次正式运行需用全新的 Linux work 目录和 evidence 输出目录：

```bash
python3 tools/run_stage09_comparison.py \
  --source-root /path/to/clean-pinned-opentitan \
  --python-env /path/to/opentitan-compatible-venv \
  --work-root /path/to/new-linux-work-directory \
  --output evidence/stage09_comparison/new-run

python3 tools/audit_stage09_comparison.py \
  --evidence-dir evidence/stage09_comparison/new-run

python3 -m unittest discover -s tests -q
```

`Full` 在本阶段明确指冻结动作池上的 round-robin；UCB 是正向 novelty 工程策略，消融将选择用 reward 均值置零。160 个数组 identity 来自已登记的 VCS 范围参考，尚未证明 Verilator/Cocotb 与原生 UVM/VCS 的采样等价。175/4,507 是已确认正向 identity 的局部结果，不是完整覆盖率；论文 cluster UCB、完整 bin identity/sample-site mapping 和 Stage 10 独立复核仍未完成。

## 剩余工作

Stage 09 工程对照通过；完整论文方法对照和 VCS/UVM 等价性仍不满足验收。下一步进入 Stage 10：独立复核实验协议、所有 evidence hashes 与结论边界，不把工程 pilot 结果提升为论文覆盖率结论。
