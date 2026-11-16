# 独立固定版本实际采样对照

已完成三个新编译的 UVM/VCS 短测试和三个 Verilator/Cocotb 配对回放，全部通过。两边接受的 TL 地址、数据、时刻、响应与读回值一致；测试 body 内逐 AON 边沿的 RTL 计数器和输出引脚一致。实际 coverage 采样存在差异，不能宣称 UVM/Cocotb 覆盖率等价。

| 用例 | VCS 退出码 / error / fatal | Cocotb 退出码 / XML | UVM 实际 samples（body 内） | Cocotb samples（body 内） |
| --- | --- | --- | --- | --- |
| wakeup | 0 / 0 / 0 | 0 / PASS | 20 | 23 |
| bark | 0 / 0 / 0 | 0 / PASS | 26 | 32 |
| bite | 0 / 0 / 0 | 0 / PASS | 26 | 32 |

UVM 全程另有每个 run 在 t=0 的两个初始化 pin samples，共 78 次实际调用；body 内比较为 72 对 87。初始化记录没有删除，完整保留在 `vcs-case-*.json`。body 前的初始化采样不包含在本轮配对结论中。

## 来源与边界

OpenTitan 固定为 `9f20940d494a223cc950a5b98f748fb28109d458`。构建前核验 10,514 个 Git blobs，构建后逐文件复验。只声明四个文件改动：原 scoreboard 九个 `.sample()` 点和 TL callback 的日志、TB 的时钟/复位/RTL 观察日志、确定性 smoke 序列，以及 base test 中固定 50 MHz 快时钟的诊断配置。AON 为 200 kHz，CDC 随机延迟关闭，sleep/lc 为 0，seed=1。两边回放同一绝对 ps 时间线，无拟合平移；完整随机化 TL base 地址也照原值输入，adapter 单独使用 CSR offset。

原 scoreboard 的功能逻辑没有修正，wakeup 低字读两次的问题保留。全部 patch、修改前后哈希、simv 哈希、源码证明、tool hashes 和退出状态可查。未复用旧 simv。VCS P-2019.06-SP1，Verilator 5.020，Cocotb 1.9.2。完整日志、VDB、许可证、密钥、二进制和私有路径未提交。

## 实测差异

1. **配置镜像初值不同。** 原 scoreboard 的本地 `wdog_regwen` 是未赋初值的 `bit`，因此为 0；现有 Cocotb adapter 按寄存器复位值初始化为 1。本测试未写该寄存器，三组各 14 个 `timer_cfg_cg` 样本均保留这一差异。不能直接把 RTL 复位值当成源码局部镜像的初值。
2. **wakeup 元组数值不同。** t=426,707,766 ps，RTL 计数器为 2，原 scoreboard 把两次低字读数组合成 8,589,934,594（`0x0000000200000002`），Cocotb 使用真实 RTL 值 2。这是固定参考逻辑的可复现差异。
3. **timer 调用次数不同。** UVM wakeup 实际仅采到两次，且都在首次 count 边沿；Python scheduler 记录五次。bark/bite 也存在重复首次调用、后续缺失及重启差异。producer 的 count/expiry 日志含重复行；实际 `.sample()` 的不同 `seq` 也证实了重复调用，不能把它们作为日志重复简单删除。在本轮 count+expiry 同时出现的边沿，观察到的实际 timer sample 数为 0。完整控制流原因仍需独立 variant 验证，不能仅用 producer 消息推断 sample 次数。
4. **引脚次序不同。** UVM `foreach` 按 packed vector 的 1→0 遍历，adapter 为 0→1。同一时刻的 pin 样本多重集合均相等，严格调用顺序不同；每组 `intr_cg` 读回样本则逐项完全相等。报告同时保存严格次序与同时间多重集合比较。

因此，这轮已经证明三组确定刺激下 RTL 行为一致，并暴露了原参考和移植采样器的具体差异。它没有补齐 update/restart/prescale/sleep/reset 矩阵，也没有覆盖 228 个 shared/non-AON definitions；`complete_parity_verified=false`、coverage credit=0、full coverage=null。

## 文件与重放

- [audit.json](audit.json)：逐组次数、实际时刻、字段差异、bus/RTL 比较和输入哈希。
- [source-attestation.json](source-attestation.json)、[post-build-source.json](post-build-source.json)、[instrumentation.patch](instrumentation.patch)：构建前后源码及声明改动。
- [attempts.json](attempts.json)：保留前两次 Git 元数据准备失败、第三次随机 96 MHz 的三次 PASS 诊断和第四次固定 50 MHz 的三次 PASS。第三次完整 compact capture 保留在 `earlier-randomized-clock-capture/`，不混入本轮配对。
- `vcs-case-0/1/2.json`：实际采样记录与控制消息分开保存。
- `cocotb-case-*/`、[cocotb-manifest.json](cocotb-manifest.json)、[cocotb-export.json](cocotb-export.json)：独立 RTL 回放、adapter raw samples、XML 与哈希。XML 只规范化了源码文件路径，原始和公开 XML 哈希均保留。
- [工具说明](../../../tools/stage10_sample_parity/README.md)：执行入口与新目录约束。

本仓库根目录可离线重放审计：

```bash
python3 -m tools.stage10_sample_parity.audit \
  --evidence-dir evidence/stage10_independent_sample_parity/2026-11-16-v1 \
  --output build/stage10-actual-sample-replay.json
python3 tools/stage10_full_simulation_preflight.py --output build/stage10-preflight.json
```

下一步在**新的 adapter/schema 和参考修复 variant**中核验这些差异，原始固定版证据保持原样。Full 前五项门禁仍未通过；这次没有启动 full 仿真。
