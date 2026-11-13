# 阶段 08：在线覆盖闭环

状态：count-event trace v2 已实测；160 个数组 bin 的 VCS 参考边界已接入审计，但阶段门仍为 BLOCKED，尚未启动在线调度。

## 已完成：readiness preflight

此前预检汇总了 4,507 个 bin 定义、Stage 06 矩阵、Stage 07 调度许可和旧版采样点映射。新的 trace v2 已加入三个计数事件 covergroup；当前按 pinned scoreboard 的启动延迟和倒计时调度取样，并直接观察 RTL 计数值。计数事件时序仍未与 UVM/VCS 实测逐项比对，自动 bin/cross 分区和 shared identity mapping 仍未解决。`resets_cg` 已由 [`configs/conditional-reset-audit.json`](../configs/conditional-reset-audit.json) 确认在 `num_edn=0` 的 AON Timer 配置中不适用。Stage 06 与 Stage 07 的旧门禁结果不会由本次 trace 自动升级。

因此本轮交付是 count-event trace v2 的固定 RTL 集成、`resets_cg` 适用性审计、Stage 06 partial 矩阵重建和更新后的 preflight；这不是 online coverage feedback 的实测。最新门禁结果见 [`evidence/stage08_preflight/2026-11-13-conditional-reset-audited/readiness.json`](../evidence/stage08_preflight/2026-11-13-conditional-reset-audited/readiness.json)。

命令、版本、门禁结果和继续实施条件记录于 [`实施记录.md`](实施记录.md)。

## 后续目标
真实仿真反馈和连续补位。

## 输入与产物
输入：scheduler 与 Verilator/Cocotb worker。
产物：事件链、vectors、coverage curve、audit。

## 验收
反馈来自已完成真实 run；失败计入预算且不领奖励。

实际命令、版本、seed、运行 ID、失败处理和局限写入本目录的 `实施记录.md`。没有仿真与复核证据时不标记完成。
