# 阶段 08：在线覆盖闭环

状态（2026-11-14）：**限定范围的在线 pilot 已实跑通过；完整论文闭环尚未完成。**

## 已完成：真实在线 pilot

- 固定 OpenTitan `9f20940d494a223cc950a5b98f748fb28109d458`；Verilator 5.020 / Cocotb 1.9.2 / FuseSoC 0.5.dev0 / Edalize 0.4.0。
- 18 次独立单用例真实仿真，seed 1，六个冻结配置动作各执行 3 次，18/18 PASS。
- 前 6 次遍历动作；后 12 次使用已完成 run 的奖励和次数重新计算 UCB 后选择。每轮选择先写盘，完成仿真后才能更新状态。
- 330 条 raw samples，累计 20 个正向 identity；4,487 unknown、0 inferred misses。前六次分别新增 5、4、0、3、4、4，后十二次没有新增。
- `timer_cfg_cg` 的 prescale/bark/bite/wkup 实时数值已按 `references/array_bin_ranges.v1.json` 分类并写入 `reference_array_bin_memberships`；状态仍明确为 Python 参考分类，native 等价性未宣称。
- 每轮保存 selection、实际 Cocotb XML、trace、稀疏正向 vector、退出码、奖励和前一条结果的哈希；完整日志和原始 XML 保留在本地 work 目录。公开 XML 将路径规范化为仓库相对路径，并同时登记原始/公开 XML 的哈希。
- 缺少 XML、失败、超时、trace 元数据不匹配都不能领覆盖奖励；失败同样消耗预算。

证据：[summary](../evidence/stage08_online_pilot/2026-11-14-v9/summary.json)、[覆盖观察曲线](../evidence/stage08_online_pilot/2026-11-14-v9/coverage_curve.csv)、[逐轮回放](../evidence/stage08_online_pilot/2026-11-14-v9.replay-audit.json)。

## 与论文方法的边界

策略 `testcase_ucb_positive_novelty_v1` 的 reward = 本轮新增可确认 identity 数 / 4,507；UCB = 该 action 历史平均 reward + 0.01 × sqrt(2 ln(已完成次数) / 该 action 次数)。失败奖励为 0，仍进入次数统计。

“选择 → 真实 RTL 仿真 → trace 校验 → 正向覆盖反馈 → 下一次选择”已经接通。78-cluster mapping 只用于记录命中属于哪些 cluster，**没有参与选择**；论文自信息评分、residual cluster prior 和 cluster UCB 尚未接通。

六个 action 和刺激均为确定性。本次前六轮 warmup 后选择了高奖励 action，不能据此声称优于 Random 或 Full；首次编译计入首个 attempt 的 wall time，也不能直接用于方法效率对照。20/4,507 只是已确认命中的下界，不是完整功能覆盖率。

原生 SystemVerilog covergroup 不是 Python/Cocotb pilot 的前置条件。完整论文复现仍需完整 identity bridge、live 分类器和采样对照、shared coverage、exact vectors 以及论文调度算法。最新 [完整论文门禁](../evidence/stage08_preflight/2026-11-14-full-paper-scope/readiness.json) 不再被解释为“不能进行任何在线实验”。

## 复现命令（WSL Ubuntu）

仓库根目录执行；每次使用新 work/output 目录，禁止覆盖历史结果。

```bash
python3 tools/run_stage08_pilot.py \
  --source-root /path/to/clean-pinned-opentitan \
  --python-env /path/to/opentitan-compatible-venv \
  --work-root /path/to/new-linux-work-directory \
  --output evidence/stage08_online_pilot/my-new-run

python3 tools/audit_stage08_pilot.py \
  --evidence-dir evidence/stage08_online_pilot/my-new-run \
  --output evidence/stage08_online_pilot/my-new-run.replay-audit.json

python3 -m unittest discover -s tests -q
```

协议：[configs/stage08-pilot.json](../configs/stage08-pilot.json)。修改刺激、工具或覆盖定义时创建新 protocol/run。v1-v8 调试试跑保留在本地忽略目录 `build/stage08-development-evidence/`，公开结果以最终 v9 为准。

## 后续工作

1. 扩展参数化动作和 live coverage，突破当前六个配置 action 的命中平台。
2. 补齐论文覆盖映射、信息评分和 cluster UCB。
3. 固定输入/seed/预算/worker 后执行第 09 步 Random、Full 和消融；最后进行第 10 步复核。

历史记录及本轮更正见 [实施记录](实施记录.md)。
