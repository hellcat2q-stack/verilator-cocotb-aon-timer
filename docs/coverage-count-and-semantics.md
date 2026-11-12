# 覆盖数与采样语义

原仓库 stage06 manifest 记录 4,507 个详细 canonical bin columns；URG dashboard 记录 4,525 expected groups。两者相差 18，是不同报告口径。本项目以 4,507 个逐项列作为 mapping 目标，4,525 作为原 URG 汇总参考。

每个 Python bin 应保留稳定 identity、covergroup/instance scope、coverpoint/cross、取值边界、权重/排除和 sample 时间。Cross 的成员必须在同一次 sample 时满足，不能将不同时间的命中拼起来。

验证顺序：静态定义映射、边界值、cross 同拍/异拍对照、采样来源追踪和小型真实仿真。若无法逐项映射，更新 schema 并披露差异，不强行补齐 bin 总数。
