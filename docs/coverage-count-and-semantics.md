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

`timer_cfg_cg` 的 160 个数组 bin 已确认数组索引与声明取值域，但来源 manifest 没有各索引 bin 的精确边界。旧 Stage 06 canonical label 只与 341 列直接匹配；重复的 `*X*`、`values:{...}` 标签及 shared-group 实例需要单独建立、验证一对一映射。Python trace 保留原始整数和 exact sample tuple，因此定义参考已增加，但当前仍不生成完整 4,507 维 sample vector。

完成 exact sample mapping 后，需逐项验证 identity、covergroup/instance scope、coverpoint/cross、边界值、illegal/ignore/weight 规则和采样时机，再与 4,507 canonical 列一一对账。4,525 URG 汇总继续独立记录；计数相同也不作为语义等价的证据。
