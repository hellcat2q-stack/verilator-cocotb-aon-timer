# 阶段 01：环境与源码版本锁定

状态：源码、coverage 参考口径和工具版本已登记；固定版本源码已由阶段 02 使用。

OpenTitan revision 固定为 `9f20940d494a223cc950a5b98f748fb28109d458`，tree SHA-1 为 `4229b5d334cf7c02996856ddbdf625989b5a6b58`。原项目 manifest 中记录的归档 SHA-256 为 `9f96395245d9a73de7608a06c47a9b0212b08cf151475dbc5f50c79ea8aaf280`；本次 WSL 源码包 SHA-256 为 `3378fe535b6e0ff7676b706bee85113185f5691d0f345e975a021857562f8fdc`。文件级校验与固定 revision 对应，两个归档哈希按各自来源单独记录。Coverage 参考口径分开登记：4,507 canonical bins 和 4,525 URG dashboard expected groups。

本机已安装环境为 Ubuntu 24.04、Verilator 5.020、Cocotb 1.9.2、Python 3.12.3、FuseSoC 2.4.5、Edalize 0.6.3。阶段 02 实测使用单独环境中的 lowRISC FuseSoC `ot-0.5.dev0` 和 Edalize 0.4.0，以匹配该 revision 的 FuseSoC generator API；依赖清单在 `configs/stage02-requirements.txt`。

本阶段已在固定源码上完成 Verilator/Cocotb smoke；尚未证明 Cocotb 模型与 UVM coverage 等价。
