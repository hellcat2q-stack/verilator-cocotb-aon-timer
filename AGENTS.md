# 项目约定

- 本分支只记录 Verilator + Cocotb 移植结果；不混入其它分支的仿真 run。
- 固定 OpenTitan revision 为 `9f20940d494a223cc950a5b98f748fb28109d458`。修改源码、覆盖定义或工具时建立新 schema/run。
- 4,507 canonical bins 与 4,525 URG 汇总参考分开记录；未经采样语义复核不得声称与 UVM/VCS 等价。
- 使用独立源码副本，不修改用户现有 OpenTitan checkout。
- 没有仿真证据不得写 PASS。计划、静态检查和历史 VCS 数据不算本分支实测。
- 每个 run 记录 revision、schema、testcase、seed、退出状态和覆盖向量；保留失败记录。
- 不提交 VCS VDB、simv、许可证、密钥、private path 或大型完整日志。
- 脚本放入对应阶段并登记；阶段通过审查后单独提交。