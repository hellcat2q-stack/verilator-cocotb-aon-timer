# 阶段 02：Verilator构建与RTL入口

状态：待开始。

## 目标
固定版本 AON Timer RTL 与 Cocotb smoke。

## 输入与产物
输入：source lock、官方 FuseSoC cores 和 WSL 工具。
产物：build 命令、RTL bridge、smoke log 与哈希。

## 验收
固定源码可构建；TL-UL 写读、双时钟、复位 smoke 通过。

实际命令、版本、seed、运行 ID、失败处理和局限写入本目录的 `实施记录.md`。没有仿真与复核证据时不标记完成。
