# verilator+cocotb复现aon timer

## 目标

在固定 OpenTitan AON Timer RTL 上用 Verilator + Cocotb 运行测试，移植官方测试刺激、覆盖采样与反馈调度，建立可审计的开源实验链路。旧 VCS 命中数不会作为 Cocotb 结果复用。

**阶段 09 工程对照已实跑并独立审计通过。** 固定 RTL 上完成 288 次 Verilator/Cocotb 仿真（UCB、Random、round-robin Full、关闭 reward 消融；三个选择种子），288/288 PASS、16,515 条 samples。UCB/Full/消融均确认 175 个正向 identity；Random 为 160–168。4,332–4,347 个 identity 仍为 unknown，未推断 miss。逐次 XML、trace、向量、决策与审计见 [Stage 09 证据](evidence/stage09_comparison/2026-11-14-v1/summary.json) 和 [replay audit](evidence/stage09_comparison/2026-11-14-v1/replay-audit.json)。这是动作池上的工程对照，不是完整论文调度，也不证明 VCS/UVM 覆盖等价。

**覆盖率口径：**目前不能报告 full coverage rate。Stage 09 UCB seed 1 有 175/4,507 个正向 identity（3.8828% 的目录比例），其余 4,332 个是 unknown，不是 miss。4,507 canonical identities 与 4,525 URG dashboard reference 分开统计。见[阶段 10 复核](10_最终复核与报告/README.md)。

## 固定参考

| 项目 | 值 |
| --- | --- |
| OpenTitan | lowRISC/OpenTitan |
| Revision | `9f20940d494a223cc950a5b98f748fb28109d458` |
| 原仓库 manifest 归档 SHA-256 | `9f96395245d9a73de7608a06c47a9b0212b08cf151475dbc5f50c79ea8aaf280` |
| 本次 WSL 解压包 SHA-256 | `3378fe535b6e0ff7676b706bee85113185f5691d0f345e975a021857562f8fdc` |
| Canonical bin matrix | 4,507 |
| 原 URG dashboard 汇总 | 4,525，单独保留 |
| 已安装环境 | Ubuntu 24.04、Verilator 5.020、Cocotb 1.9.2、Python 3.12.3、FuseSoC 2.4.5、Edalize 0.6.3 |
| 阶段 02 实测环境 | Verilator 5.020、Cocotb 1.9.2、Python 3.12.3、lowRISC FuseSoC `ot-0.5.dev0`、lowRISC Edalize 0.4.0 |

详见 [源码锁](01_环境与源码版本锁定/source_lock.json)。

## 阶段计划

| 阶段 | 工作 | 状态 |
| --- | --- | --- |
| 01 | 固定源码、bin 参考口径、工具版本 | 完成 |
| 02 | Verilator 构建与 Cocotb RTL smoke | smoke 通过；Lint/coverage 迁移待后续阶段 |
| 03 | 移植覆盖模型并核验 bin/sample 语义 | 4,507 个定义已导入；live Python 参考数组分类已接入 trace；完整 legacy identity、shared 采样和 UVM/VCS 时序对照待补 |
| 04 | 移植测试序列和关键 scoreboard 检查 | 固定 4/4 功能序列接入 partial raw sample trace；完整 vector 与 stress-all 待后续 |
| 05 | 冻结测试池、seed 并生成初始语料 | frozen pool 校验 trace hashes/sample counts；1 suite、4/4 PASS；导出稀疏部分命中记录 |
| 06 | 生成 bin-by-run 矩阵并审计 | Stage 05 partial matrix 仍为 13 known hits；Stage 08 pilot 可确认 20 个正向 identity、4,487 unknown，0 推断 miss；完整 coverage 阶段门未通过 |
| 07 | 接入聚类、信息评分与 UCB 调度 | 4,507 identities → 78 clusters 已回放；论文信息评分与 cluster UCB 待补；另有 Stage 08 testcase UCB pilot 已运行 |
| 08 | 在线仿真和 coverage feedback 闭环 | action-boundary pilot 完成 18 次真实仿真与逐轮反馈，18/18 PASS、330 样本、20 positives；完整论文闭环尚未完成 |
| 09 | Random、Full 和消融对照 | 工程范围 288 次 RTL 对照及独立 replay audit 完成；完整论文方法对照仍待完成 |
| 10 | 独立复核与最终报告 | Stage 09 工程证据复核完成；完整论文 full coverage 仍不可报告 |

## 文件管理

- `01–10`：阶段 README、实施记录和证据索引。
- `configs/`：源码、工具、测试池和运行协议。
- `docs/`：路线图、迁移映射、coverage 语义。
- `tools/`：build、runner、parser 和审计工具。
- `evidence/`：公开摘要、vectors 和哈希。
- `references/`：来源登记；不复制 OpenTitan 全仓。

coverage 数量相同不代表语义等价。必须验证 bin identity、边界、采样时机、cross 同次采样、实例展开和排除规则后，才能讨论与 VCS 结果的可比性。阶段只有在真实运行并复核后才标记完成。

阶段 10 工程证据复核已完成。若要报告完整论文覆盖率，仍需补齐 bin identity、sample-site/采样语义、exact vectors 与 VCS/UVM 对照；阶段 09 的工程对照结果不能当作论文覆盖率或效率结论。

## 阶段 02 快速运行

在 WSL Ubuntu 中先将 OpenTitan 固定版本解压到 Linux 文件系统，然后设置 `SOURCE_ROOT` 和 Linux 文件系统上的 `WORK_ROOT`。首次运行执行 `bash tools/setup_stage02_env.sh`，随后执行 `RANDOM_SEED=1 bash tools/run_stage02_smoke.sh`。阶段环境单独固定 OpenTitan 兼容版 FuseSoC/Edalize；不要用系统中已安装的 FuseSoC 2.4.5 替代。详细命令、验收范围及限制见 [阶段 02 记录](02_Verilator构建与RTL入口/README.md)。
