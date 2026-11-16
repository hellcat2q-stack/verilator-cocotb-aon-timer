# 修复参考采样后的三组独立对照

**修复版 UVM/VCS 与独立 Cocotb adapter 在三个短测试中逐组一致，6/6 测试 PASS。** 所有样本字段、组内顺序、绝对 ps 时间、同时间多重集合、TL 输入/响应和逐 AON 边沿 RTL 状态均匹配。不同 covergroup 在同一时刻的全局调用顺序仍不同，完整原版/全场景等价尚未建立。

| 用例 | 修复版 UVM body samples | 新 Cocotb body samples | 逐组字段/顺序/时刻 | VCS error/fatal | Cocotb XML |
| --- | --- | --- | --- | --- | --- |
| wakeup | 22 | 22 | 一致 | 0 / 0 | PASS |
| bark | 30 | 30 | 一致 | 0 / 0 | PASS |
| bite | 30 | 30 | 一致 | 0 / 0 | PASS |

三组 body 内合计 **82/82**。UVM 另有每个 run 在 t=0 的两个 pin 初始化 samples，保留在原始记录中；全程调用为 88。body 前初始化不包含在本轮配对结论中。实际触发 6 个 AON covergroup；`intr_test_cg` 尚未纳入本轮刺激。

## 三个参考修复及独立原因验证

`pinned-sampling-fixes-v1` 基于 `9f20940d494a223cc950a5b98f748fb28109d458`，独立导出并在构建前后核验 10,514 个源码 blobs。RTL 没有修改；三组刺激、seed=1、50 MHz 快时钟、200 kHz AON、关闭 CDC 随机延迟均沿用已冻结短测协议。

1. **修复复位 fork 清理作用域。** 原代码把内层 timer fork 与 `disable fork` 放成外层 fork 的两个子线程；清理操作没有拥有 timer 后代。修复后用一个 `begin...end` child 包住两者。独立 [fork-probe.json](fork-probe.json) 在一次复位后发送 5 个 tick：原拓扑执行 10 次，修复拓扑执行 5 次。AON 三组控制记录中也不再出现相同 producer 事件重复。
2. **修复 wakeup 高字读取。** 原代码把低字读两次；现在高 32 位来自 `wkup_count_hi`。第一 count 时刻 426,707,766 ps，修复前记录 `0x0000000200000002`，修复后与实际 RTL 值 2 一致。没有改变 bin 定义。
3. **改为等待命名事件本身。** 在本次 VCS P-2019.06-SP1 的独立 [event-probe.json](event-probe.json) 中，5 次触发对应 `@(event.triggered)` 接收 1 次、`@(event)` 接收 5 次。这是该工具版本的实测，不泛化为所有仿真器的结论。修复后的 AON 采样恢复到后续 count 边沿；同一时刻 count+expiry 两个 producer 唤醒一次实际 consumer，样本包含已置位的 expiry 状态。

完整差异在 [instrumentation.patch](instrumentation.patch)，仅修复差异在 [reference-fixes.patch](reference-fixes.patch)，[instrumentation.json](instrumentation.json) 记录每个文件的修改前后哈希。[source-attestation.json](source-attestation.json) 与 [post-build-source.json](post-build-source.json) 证明除声明的四个测试/日志/scoreboard 文件外，固定源码 blobs 均保持一致。

## Python 修复与采样边界

新建 `PinnedSamplingFixedAdapterV1`，没有修改历史 adapter 或模型。配置镜像 `wdog_regwen` 从原 SV 局部变量的初值 0 开始，独立维护 RAL 的复位值 1 与 W0C 状态；pin 按原 packed vector 的 1→0 顺序采样；保留 scheduler 的 producer kinds，但在同一边沿只生成一次原生命名事件 consumer 样本。全部 timer 数值仍读取独立 Verilator RTL 探针，不读取 UVM 的样本元组或命中数。

新 trace schema 为 `aon_timer_pinned_sampling_fix_trace_v1`，variant 身份及 raw RTL 值都有记录，canonical vector 为空，identity credit 被清空，coverage credit=0。原版 [72/87 诊断](../../stage10_independent_sample_parity/2026-11-16-v1/README.md) 保留原样，不能把修复后的匹配追溯为原版等价，也不能并入 Stage 09 的覆盖率结果。

跨 covergroup 的同时间全局顺序仍不同，报告中的 `global_invocation_order_equal=false` 没有隐藏。组内顺序和同时间多重集合均相同；本轮没有验证更广的更新、重启、prescaler、sleep/pause、复位矩阵或 shared groups，因此 `complete_parity_verified=false`、`original_reference_parity_verified=false`、full coverage=null。

## 文件与离线复核

- [audit.json](audit.json)：真实样本对照、producer 唯一性、两个原生探针、source/runtime/XML hashes 和范围限制。
- [execution.json](execution.json)：本次构建及运行退出码、实际 compiler/runtime 版本、输入/完整日志哈希；VDB、simv、许可证、私有路径和完整日志不提交。
- `vcs-case-*.json`：实际 sample 和 control 消息分开保存，VCS 三组退出码均为 0。
- `cocotb-case-*/`、[cocotb-manifest.json](cocotb-manifest.json)、[cocotb-export.json](cocotb-export.json)：独立回放、raw trace、原始及规范化 XML 哈希。
- [工具登记与运行说明](../../../tools/stage10_sample_fix/README.md)。

```bash
python3 -m tools.stage10_sample_fix.audit \
  --evidence-dir evidence/stage10_sample_fix/2026-11-16-v1 \
  --output build/stage10-fixed-sample-replay.json
python3 tools/stage10_full_simulation_preflight.py --output build/stage10-preflight.json
```

新的 [v6 preflight](../../stage10_full_simulation_preflight/2026-11-16-v6/preflight.json) 离线重放原版差异和修复版匹配两套证据。Full 仿真没有启动，五项门禁仍未解除；下一步扩展实际采样矩阵，而不是把三个短测提升成完整 parity。
