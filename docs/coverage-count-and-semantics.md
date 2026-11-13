# 覆盖数与采样语义

原工程记录 4,507 个 canonical bin columns 和 4,525 个 URG dashboard groups，属于不同报告口径。当前仓库已从原 stage06 `coverage_bin_by_run.csv` 的表头提取并核验 4,507 个唯一 identity，清单见 `references/canonical_bin_ids.txt`，来源校验信息见 `references/canonical_bin_catalog.json`。仅提取表头；没有复制历史 run coverage 值。4,279 个 identity 属于 AON Timer covergroups，另 228 个属于共享 DV/TL 等 covergroups。

## 当前源码映射

`aon_timer_env_cov.sv` 定义 4 个 AON Timer covergroups；`aon_timer_env_cov` 同时继承 CIP base covergroups。完整字段、cross 和采样点见 `configs/coverage_schema.json`。关键时序是：

- 配置组在有效 CSR 写地址阶段采样，而且 scoreboard 本地字段更新发生在该 sample 之后。
- wakeup/bark/bite 组在对应 AON 计数事件中采样，计数值通过 backdoor 从 RTL 读取。
- interrupt 状态在 CSR 数据阶段读取时采样；interrupt test 在 CSR 写入时采样；pin 组按异步 pin 变化采样。
- 固定 revision 的 base scoreboard 对同一 TL 事务分别调用 `process_tl_access` 的地址与数据阶段；AON Timer 覆写里的 `intr_test` case 没有限制 channel，因此一次 `INTR_TEST` 写会在两个阶段各采 WKUP/WDOG 一次。Cocotb raw trace 保留这四次调用，不能按一次软件写合并。
- 交叉覆盖的所有成员保存在同一条 sample record 中。不能跨记录合并 coverpoint 值。

## Bin identity 状态

identity 清单冻结了每个 canonical 列的完整 label。`references/bin_definitions.v1.json` 从与固定 revision 匹配的详细定义清单中提取了 4,507 个类型 bin 定义，包含 64/32-bit auto-bin 实际区间和全部 3 个 AON Timer cross 的成员组合；自动分区连续无重叠，cross 组合数量分别为 1,024、512、512。此文件只保存定义，不含历史 run 命中数。

`timer_cfg_cg` 的 160 个数组 bin 现已从兼容项目 VCS `vectors.csv` 的首行表头导入逐项区间，保存于 `references/array_bin_ranges.v1.json`。导入器只读取表头，不读 run rows 或 hit counts；preflight 重新核对每项源码索引、canonical identity、声明域、连续性及输入哈希。它们是固定源码定义下的 VCS 参考分区，当前尚未证明与 Verilator/Python coverage 实现等价。另一个独立审计将区间用于 Stage 05 已校验的 78 条 `timer_cfg_cg` 原始配置样本，识别出 40 次正向归属观察、涉及 6 个数组 identity；结果存放于 `evidence/stage03_array_bin_observations/`，没有合并进 Stage 06 vector。旧 Stage 06 canonical label 仍只有 341 列可按直接标签匹配；重复的 `*X*`、`values:{...}` 标签及 shared-group 实例需要建立、验证一对一映射。当前仍不生成完整 4,507 维 sample vector。

完成 exact sample mapping 后，需逐项验证 identity、covergroup/instance scope、coverpoint/cross、边界值、illegal/ignore/weight 规则和采样时机，再与 4,507 canonical 列一一对账。4,525 URG 汇总继续独立记录；计数相同也不作为语义等价的证据。
