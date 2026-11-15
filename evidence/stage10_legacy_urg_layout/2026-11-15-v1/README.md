# 原 Stage 06 URG 布局恢复与身份审计

2026-11-15 从原论文项目的 `stage06_conversion_20261101T_v10` 恢复五份报告，共 80 份 `grp*.html`，下载内容逐一对照服务器 SHA-256。原 CSV、manifest 哈希与当前冻结参考一致。URG 为 P-2019.06-SP1，VCS compiler/runtime 为 P-2019.06-SP1_Full64，版本分别从原 `urg.log` 和 `original_g0` 对应的 VCS `run.log` 确认。恢复记录见 [recovery.json](recovery.json)。

公开布局 [layouts.json](layouts.json) 仅导出定义标签、NUMBER、组/coverpoint 名、页面文件名和 SHA-256。原始 HTML 和运行日志保留在 ignored build 目录，原有 `COUNT`、score、测试名、服务器路径不进入公开布局。没有启动新 VCS/RTL 仿真。

首份 `original_g0` 的定义标签准确复现冻结的 4,507 列。旧转换器按 coverpoint/cross 中的行位置把后续报告写入首份报告的列，而报告的 covered/uncovered 分组会改变行序。

| 对照报告 | 展开 identity 数 | 明确的同位置身份冲突 | 按语义匹配的明确变量数 |
| --- | ---: | ---: | ---: |
| original_g1 | 4507 | 126 | 345 |
| original_g10 | 4507 | 114 | 345 |
| original_g20 | 4507 | 83 | 345 |
| original_g30 | 4507 | 236 | 345 |

合计 559 处是四份对照报告的冲突次数，不是去重后的受影响 bin 数。直接反例：`timer_cfg_cg.wdog_regwen_cp` 在首份报告中的行序为值 1、值 0，在 `original_g1` 中为值 0、值 1，按原位置写入会交换两列。更多反例和来源哈希见 [audit.json](audit.json)。

新的 `align_by_semantics` 对唯一明确变量名或 singleton 值生成配对；它不按位置对齐，不解析压缩行内部次序，不给 wildcard cross 或重复名字猜身份。审计状态为 `UNSAFE_LEGACY_POSITIONAL_BRIDGE`；这是检出了旧映射错误，并非审计器执行失败。345 个可配对变量仍不是完整映射，也不是命中数。

在仓库根目录运行：

```bash
# 从公开布局离线重放，无需学校服务器、VCS 或第三方 Python 包
python3 tools/audit_legacy_urg_layouts.py \
  --layouts evidence/stage10_legacy_urg_layout/2026-11-15-v1/layouts.json \
  --output-dir build/stage10-legacy-urg-replay

# 有原始 HTML 时，可重新导入标签布局
python3 -m pip install -r configs/stage10-requirements.txt
python3 tools/audit_legacy_urg_layouts.py \
  --reports-root build/stage10-legacy-urg-20261115 \
  --output-dir build/stage10-legacy-urg-reimport

python3 -m unittest discover -s tests -q
```

全仓 105/105 单测通过。从原始 HTML 导入和从公开布局离线重放生成的 `layouts.json`、`audit.json` 分别逐字节相同。另用原转换器复核，五份报告的展开 identity 和先后次序均与公开布局一致。各 JSON 的 SHA-256 sidecar 随目录保存。Stage 09 现存证据再次独立重放通过，288/288 次记录通过，正向观察数与原报告相同；这次重放不是新的 RTL 仿真。

下一步以固定源码定义的 `definition_id` 为稳定键实现原始样本分类，再输出新 schema 的向量。2,076 个旧 occurrence 顺序候选继续不获 credit；本次不增加覆盖观察、不推断 miss，也不修写其他仓库。Stage 09 的 175 个正向观察/4,332 个 unknown 保持原口径，full coverage rate 仍为不可报告。
