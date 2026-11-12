# 阶段 01：环境与源码版本锁定

状态：源码、coverage 参考口径和工具版本已登记；新工程构建与 smoke 留待阶段 02。

OpenTitan revision 固定为 `9f20940d494a223cc950a5b98f748fb28109d458`，归档 SHA-256 为 `9f96395245d9a73de7608a06c47a9b0212b08cf151475dbc5f50c79ea8aaf280`。Coverage 参考口径分开登记：4,507 canonical bins 和 4,525 URG dashboard expected groups。

WSL 环境为 Ubuntu 24.04、Verilator 5.020、Cocotb 1.9.2、Python 3.12.3、FuseSoC 2.4.5、Edalize 0.6.3。依据为原仓库 source/bin manifest 和本机 WSL 工具查询。

本阶段没有构建固定源码，也没有证明 Cocotb 模型与 UVM coverage 等价。