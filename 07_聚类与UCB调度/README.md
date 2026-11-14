# 阶段 07：聚类与信息评分

状态：canonical-bin 聚类和确定性回放已实现；Stage 06 已有 sparse partial hits，但其余 bins 为 unknown，coverage 信息评分、UCB 先验及调度仍不可启用。

## 本阶段已做

- 从 `references/canonical_bin_ids.txt` 读取固定的 canonical identities；算法只使用 bin 名称的语义字段，不把阶段 06 的 `?` 当作 0。
- 移植原仓库选定的 `dbscan_clustering_new2` 特征提取、权重、分层 DBSCAN 参数和最大 cluster 大小 256。实现使用 Python 标准库，不需在 Cocotb 环境安装 NumPy、pandas 或 scikit-learn。
- 连续运行两次聚类并比较结果，输出 `clusters.json`、`bin_to_cluster.csv`、分区统计、参数、调度输入占位文件和 SHA-256 审计。
- 调度输入明确记录 partial vector 无法确认 misses 或剩余未覆盖集合；coverage state、information scores 与 cluster priors 均保持 null。

## 运行

```bash
PYTHONHASHSEED=0 python3 tools/stage07_clustering.py \
  --bin-ids references/canonical_bin_ids.txt \
  --output-dir evidence/stage07_partial \
  --max-cluster-size 256 --seed 0
```

## 验收边界

聚类 mapping 可作为通用 API 的静态输入；当前矩阵仅有 sparse known hits，没有可确认的 misses 或完整 residual set，因此不生成论文自信息分数、动态 residual prior 或 cluster UCB state。最新 count-event v2 blocker 见 [`evidence/stage07_count_event_v2_verified/scheduler_input.json`](../evidence/stage07_count_event_v2_verified/scheduler_input.json)。此阶段不表示完整 coverage vector 或论文覆盖率结果已完成。

2026-11-14 已单独完成 [Stage 08 positive-hit pilot](../08_在线覆盖闭环/README.md)：testcase UCB 只使用正向新命中反馈，12 次真实仿真通过，不推断 omitted bins 为 miss。78-cluster mapping 在 pilot 中只记录命中归属，未用于选择，不改变本阶段论文信息评分仍未完成的状态。

算法来源和版本记录见 `实施记录.md`；静态聚类 mapping 见 `evidence/stage07_initial/`，最新 exact-vector blocker 见 `evidence/stage07_partial/`。
