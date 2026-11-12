# 阶段 03：官方覆盖模型迁移

状态：部分完成。现已导入固定 revision 对应的 4,507 个类型级 bin 定义，核验 6 组 auto-bin 区间和 3 个 cross 组合；160 个数组 bin 的单 bin 边界、旧 canonical 列一对一映射及完整逐样本采集仍待完成。

## 已完成

- 列出 AON Timer 自有 covergroup 与继承的 CIP 中断/复位 covergroup。
- 从原 stage06 矩阵表头提取并核验 4,507 个唯一 canonical identity；其中 4,279 个属于 AON Timer，228 个来自共享 DV/TL 等 covergroups。只保留表头，没有导入历史 run coverage 数据。
- 记录每个 sample 的源码调用点、条件、字段宽度、explicit/array/auto bins、cross 成员与同拍要求。
- 新增 `tools/coverage_model.py` 保存完整 raw sample tuple，不把跨时间的样本拼成 cross。
- 将可确认的 named explicit-bin hits 直接关联到 canonical identity；未解析分区仍只留 raw 值。
- 新增边界、位宽、cross 隔离、pin transition、reset sequence 单元测试。
- 复核固定 revision 的 TL A/D channel 调用路径，修正 `intr_test_cg` 的 multiplicity 记录：每笔写在地址/数据两次 scoreboard invocation 中分别采 WKUP/WDOG。
- 从固定 RTL 的确定性 Cocotb 测试保存了 CSR 与 AON pin partial raw traces；冻结语料 run 会在 manifest 中登记并验证 trace hashes 和 sample counts。

## 未完成项

最新冻结 run 的 112 条 raw samples 中，7 个 source-confirmed named-bin identities 已解析为 known hits；这是 sparse evidence，不证明完整采样或命中集合。

匹配固定源码 revision 的详细 URG 定义 manifest 现已恢复 4,507 个类型级 bin 定义，并提供 `auto_bin_max` 的实际区间及完整 cross 组合。`bins name[N]` 的数组索引和声明取值域已记录，但 manifest 没有各索引的精确边界。旧 canonical label 目前只有 341 项可直接匹配，不能据此重建完整 vector。

要完成 exact mapping，需要确定数组 bin 精确边界和 legacy identity 一对一对应，并补齐 228 个共享 DV/TL covergroups 的采样来源；之后再验证 sample timing 与完整 vector 对账。当前单元测试和定义清单审计不代表 RTL 仿真或 VCS/URG 等价。

测试命令与结果见本目录的 `实施记录.md`，摘要见 [`evidence/stage03_model_unit_summary.json`](../evidence/stage03_model_unit_summary.json)。
