# verilator+cocotb复现aon timer

## 目标

在固定 OpenTitan AON Timer RTL 上用 Verilator + Cocotb 运行测试，移植官方测试刺激、覆盖采样与反馈调度，建立可审计的开源实验链路。旧 VCS 命中数不会作为 Cocotb 结果复用。

**2026-11-17 最新复核：**Stage 09 工程矩阵 288/288 次 Verilator/Cocotb 运行通过，独立重放审计通过；source-definition 分类和 sample-site 审计也已更新。full 仿真预检仍为 `BLOCKED`，`full_simulation_started=false`、coverage credit 为 0、完整覆盖率为 `null`，所以本轮没有启动论文 full 仿真。阻塞项涉及完整 Stage 06 矩阵、legacy identity 映射、Stage 07 论文调度、shared/non-AON definitions、UVM/VCS 逐采样时序和 Verilator 数组等价性。见[最新预检](evidence/stage10_full_simulation_preflight/2026-11-17-v2/preflight.json)。

**阶段 09 工程对照已实跑并独立审计通过。** 固定 RTL 上完成 288 次 Verilator/Cocotb 仿真（UCB、Random、round-robin Full、关闭 reward 消融；三个选择种子），288/288 PASS、16,515 条 samples。UCB/Full/消融均确认 175 个正向 identity；Random 为 160–168。4,332–4,347 个 identity 仍为 unknown，未推断 miss。逐次 XML、trace、向量、决策与审计见 [最新 Stage 09 证据](evidence/stage09_comparison/2026-11-16-v2/summary.json) 和 [replay audit](evidence/stage09_comparison/2026-11-16-v2/replay-audit.json)。这是动作池上的工程对照，不是完整论文调度，也不证明 VCS/UVM 覆盖等价。

**覆盖率口径：**目前不能报告 full coverage rate。Stage 09 UCB seed 1 有 175/4,507 个正向 identity（3.8828% 的目录比例），其余 4,332 个是 unknown，不是 miss。4,507 canonical identities 与 4,525 URG dashboard reference 分开统计。见[阶段 10 复核](10_最终复核与报告/README.md)。

**2026-11-16 更新：八用例短矩阵复核通过，full 仍未启动。**VCS/Cocotb 的 8 个有界修复版案例全部通过，预检会离线重放矩阵证据及哈希，并如实记录 `8/8`；它仍是修复版短测，`complete_parity_verified=false`、coverage credit 为 0。最新 [v10 full 预检](evidence/stage10_full_simulation_preflight/2026-11-16-v10/preflight.json)动态判定门禁，列出具体未决条件和未通过检查清单。full 未启动。学校服务器的旧 1,000-run VCS 汇总标记原始日志未导出，不能用来替代逐样本参考证据。

**2026-11-15 映射复核：**已从原服务器恢复五份 URG 报告的 80 页并核验哈希。首份报告重建 4,507 列成功；四份后续报告合计检出 559 处按位置对齐的明确身份冲突，因此旧 CSV 行号不作为稳定 bin 身份。新增工具按明确 bin 名或 singleton 值对齐并拒绝压缩行猜测，证据和离线重放命令见[URG 布局审计](evidence/stage10_legacy_urg_layout/2026-11-15-v1/README.md)。这是身份审计，没有增加覆盖命中。

**2026-11-16 source-definition 分类 v2、sample-site audit、identity bridge 与 full 仿真前预检：**对 Stage 09 的 288 份 PASS raw traces（16,515 个 samples）重新分类，逐份校验 attempt/trace hash。160 个 timer array 参考分区现在已接入样本分类器，获得 42,480 次 source-definition/reference interval 匹配；范围外或不在参考 bins 中的 16,940 次观察仍为 unresolved。interrupt cross 根据完整 bin label 匹配 247 次；pin 稳定值与 transition bins 分开处理，illegal interrupt-test cross 不授予匹配。v2 共观察到 209 个 source definitions（195 个变量、14 个 cross）。新增 identity bridge 审计完整遍历 4,507 个 legacy identities：341 个 exact source-definition match、2,074 个 range-order candidate、16 个单候选 cross、2,064 个非唯一 cross candidate；所有候选均不产生 coverage credit。这些仍是源码定义/参考分区结果，不是 Verilator 原生覆盖或 VCS/URG coverage credit；coverage credit 增量为 0，175/4,507 个已确认 canonical positive、4,332 unknown 和 full coverage `null` 均不变。新增 sample-site audit 对证据目录中的 326 条 raw traces、17,743 个 samples 做结构复核，7 个 AON covergroup 的 capture protocol、字段键、same-sample cross、事件名和 count-event RTL/cadence 元数据均通过；228 个 shared/non-AON definitions 仍没有 AON adapter 映射，count-event 仍没有完整 UVM/VCS timing parity。另新增历史 `vectors.csv` 表头语义桥审计：两个 4,507 列表头均可分类为候选，但不提升 identity 或 coverage credit。学校服务器上的独立 VCS 数组边界探针完成 636/636 个可表示 boundary cases，4 个越界值均被拒绝且未截断；Python 区间与 native VCS bin interval 逐项一致，但这不证明 sample timing parity。随后又提取了四个短 UVM_HIGH 运行的 21 条 count/expiry 事件：wakeup smoke/jump、watchdog bark、watchdog bite 的主事件组均通过 cadence shape 审计；bark/bite 运行中的另一条 watchdog count 被保留为 incidental diagnostic event。该证据只证明局部计数事件形状，不授予 coverage credit，也不等价于完整 testcase waveform 或 shared-group 对照。最新预检确认定义目录 4,507 项、数组参考分区 160 项、源码/Python 640 个边界探针、VCS/Python 636 个边界探针和 Stage 09 的 288/288 replay audit 通过；full 仿真启动门禁仍为 blocked，`full_simulation_started: false`。现有 blocker 从 6 项降为 5 项。报告见[sample-site audit](evidence/stage10_sample_site_audit/2026-11-16-v2/sample-site-audit.json)、[分类结果](evidence/stage10_source_definition_classification/2026-11-16-v2/classification.json)、[identity bridge](evidence/stage10_identity_bridge/2026-11-16-v1/bridge.json)、[vector header audit](evidence/stage10_legacy_vector_header_bridge/2026-11-16-v1/audit.json)、[VCS array boundary audit](evidence/stage10_vcs_array_boundary/2026-11-16-v1/audit.json)、[UVM/VCS timing shape audit](evidence/stage10_uvm_vcs_timing/2026-11-16-v2/audit.json)和[full 仿真前预检](evidence/stage10_full_simulation_preflight/2026-11-16-v4/preflight.json)。

## 固定参考

**参考采样修复版已验证（2026-11-16）：**在新的 `pinned-sampling-fixes-v1` 中修复 reset fork 清理、wakeup 高字读取和命名事件等待；两个独立 VCS 探针分别复现原版 5 次触发只接收 1 次、复位后 5 个 tick 执行 10 次的问题，修复后均为 5 次。三组新 VCS/Cocotb 短测全部 PASS，body 内 **22/22、30/30、30/30 次采样**，每组字段、顺序和时间均一致，总线及逐 AON 边沿 RTL 状态也一致。跨 group 的同时间全局顺序仍不同，尚未扩展完整采样矩阵；原版差异、历史 adapter 和 coverage credit 保留原样。见[修复版证据](evidence/stage10_sample_fix/2026-11-16-v1/README.md)及 [v6 preflight](evidence/stage10_full_simulation_preflight/2026-11-16-v6/preflight.json)。这验证了三个短测下的修复版采样，不代表完整原版等价或最终覆盖率；full 未启动，5 项门禁仍在。

**独立实际采样对照已实跑（2026-11-16）：**从固定版本重新导出并核验 10,514 个源码 blobs，声明日志与确定性测试配置 patch，独立构建 VCS；三组短测试及三个 Verilator/Cocotb 配对回放全部 PASS。TL 输入、响应时刻与逐 AON 边沿 RTL 计数器/引脚均一致，但 body 内实际 UVM/Cocotb samples 分别为 **20/23、26/32、26/32**。已复现配置镜像 `wdog_regwen` 初值、wakeup 低字重复读取、timer 调用次数等差异；pin 同时间多重集合相同而顺序不同。见[完整证据与差异](evidence/stage10_independent_sample_parity/2026-11-16-v1/README.md)。此前 [timing 证据 v2](evidence/stage10_uvm_vcs_timing/2026-11-16-v2/README.md)只检查 producer 控制消息，仍保留作历史诊断。新 [v5 preflight](evidence/stage10_full_simulation_preflight/2026-11-16-v5/preflight.json)已离线重放实际采样对照；完整 parity 仍为 false，5 项门禁未解除，full 未启动，coverage credit 增量为 0。

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
| 10 | 独立复核与最终报告 | 原版采样差异已保留；独立参考修复版三组逐组采样匹配 22/22、30/30、30/30，两个原生原因探针通过；完整矩阵与 5 项 full 门禁待补，未启动 full |

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
