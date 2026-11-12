# 阶段 08：在线覆盖闭环

状态：readiness preflight 已运行；阶段门 BLOCKED，尚未启动在线调度或新仿真。

## 已完成：readiness preflight

预检汇总了 4,507 个 bin 定义、Stage 06 矩阵、Stage 07 调度许可和采样点映射。当前仅确认 341 个旧 identity 可按标签直接连接；160 个数组 bin 的单 bin 边界仍未确认；Stage 06 保留 7 个 known hits、4,500 个 unknown、0 个推断 miss；Stage 07 scheduler 仍关闭。采样 trace 目前只覆盖可观测的 CSR、interrupt 与 pin 调用，count-event、条件 reset 和其余 shared identity mapping 尚缺。

因此本轮交付是门禁审计和下一步清单，不是 online coverage feedback 的实测。可复核结果见 [`evidence/stage08_preflight/2026-11-12-final/readiness.json`](../evidence/stage08_preflight/2026-11-12-final/readiness.json)。

命令、版本、门禁结果和继续实施条件记录于 [`实施记录.md`](实施记录.md)。

## 后续目标
真实仿真反馈和连续补位。

## 输入与产物
输入：scheduler 与 Verilator/Cocotb worker。
产物：事件链、vectors、coverage curve、audit。

## 验收
反馈来自已完成真实 run；失败计入预算且不领奖励。

实际命令、版本、seed、运行 ID、失败处理和局限写入本目录的 `实施记录.md`。没有仿真与复核证据时不标记完成。
