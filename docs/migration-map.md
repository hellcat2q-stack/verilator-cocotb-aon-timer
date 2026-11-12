# UVM/VCS 到 Verilator/Cocotb 迁移映射

| 原流程 | 新项目计划 | 迁移工作 |
| --- | --- | --- |
| OpenTitan RTL/FuseSoC | 固定版本 RTL/core | 验证该版本 Verilator build |
| UVM top/interfaces | TL-UL、时钟/复位 bridge | config_db、virtual interface、phase 由 test harness 替代 |
| UVM virtual sequences | Cocotb coroutine tests | 约束随机、继承和 seed 重现性 |
| UVM scoreboard/RAL | Python reference checks/monitor | backdoor、CDC、RAL 逐项核实 |
| SV covergroups | Python bins/sample API | bins、cross、采样时序、排除/权重语义 |
| simv/URG worker | Verilator/Cocotb worker | runner、失败判定、runtime 与 feedback |
| VDB/XML parser | JSON/CSV adapter | 不直接套用商业格式 |
| UCB/聚类算法 | 复用算法，替换仿真 adapter | 确认策略和后端分离 |

这是迁移计划，并不表示功能已实现。
