# 阶段 03：官方覆盖模型迁移

状态：部分完成。现已导入固定 revision 对应的 4,507 个类型级 bin 定义，核验 6 组 auto-bin 区间和 3 个 cross 组合；160 个数组 bin 有 VCS 表头参考映射，且 78 条已有 `timer_cfg_cg` 样本中有 40 次正向区间归属观察、涉及 6 个数组 bin identity。该参考分区尚未证明与当前 Verilator coverage 语义等价；旧 canonical 列完整映射及逐样本采集仍待完成。

## 已完成

- 列出 AON Timer 自有 covergroup 与继承的 CIP 中断/复位 covergroup。
- 从原 stage06 矩阵表头提取并核验 4,507 个唯一 canonical identity；其中 4,279 个属于 AON Timer，228 个来自共享 DV/TL 等 covergroups。只保留表头，没有导入历史 run coverage 数据。
- 记录每个 sample 的源码调用点、条件、字段宽度、explicit/array/auto bins、cross 成员与同拍要求。
- 新增 `tools/coverage_model.py` 保存完整 raw sample tuple，不把跨时间的样本拼成 cross。
- 将可确认的 named explicit-bin hits 直接关联到 canonical identity；未解析分区仍只留 raw 值。
- 新增独立 array-range observation audit，用固定 VCS 参考区间对 Stage 05 的 78 条配置样本做正向归属标注；此审计不改变 raw sample schema，不生成 Stage 06 vector，不把未观察到的 bin 记为 miss。
- 新增边界、位宽、cross 隔离、pin transition、reset sequence 单元测试。
- 复核固定 revision 的 TL A/D channel 调用路径，修正 `intr_test_cg` 的 multiplicity 记录：每笔写在地址/数据两次 scoreboard invocation 中分别采 WKUP/WDOG。
- 从固定 RTL 的确定性 Cocotb 测试保存了 CSR 与 AON pin partial raw traces；冻结语料 run 会在 manifest 中登记并验证 trace hashes 和 sample counts。

## 未完成项

最新冻结 run 的 112 条 raw samples 中，7 个 source-confirmed named-bin identities 已解析为 known hits；这是 sparse evidence，不证明完整采样或命中集合。

匹配固定源码 revision 的详细 URG 定义 manifest 现已恢复 4,507 个类型级 bin 定义，并提供 `auto_bin_max` 的实际区间及完整 cross 组合。另有 `references/array_bin_ranges.v1.json`，从兼容项目 VCS vector CSV **仅读取表头**，为 160 个 `bins name[N]` 索引记录连续且无重叠的数值区间，并与固定源码定义及 canonical identity 对齐；不包含历史运行行或 hit counts。单独审计 Stage 05 的有效 raw traces 后，78 个配置样本中有 40 次数值落入参考数组区间，对应 6 个不同 array identity；这些只作为正向参考归属证据，不并入现有 sparse vector。此区间仍需验证当前 Verilator/Python coverage 实现采用同一边界。旧 canonical label 目前只有 341 项可直接匹配，不能据此重建完整 vector。

要完成 exact mapping，需要验证 VCS 参考数组边界在当前实现中的语义，并建立剩余 legacy identity 一对一对应；还要补齐 count-event、conditional reset 与 shared DV/TL covergroups 的采样来源，之后验证 sample timing 并对完整 vector 逐列对账。当前单元测试和定义清单审计不代表 RTL 仿真或 VCS/URG 等价。

测试命令与结果见本目录的 `实施记录.md`，摘要见 [`evidence/stage03_model_unit_summary.json`](../evidence/stage03_model_unit_summary.json)。
