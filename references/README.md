# 来源索引

- OpenTitan：lowRISC/OpenTitan revision `9f20940d494a223cc950a5b98f748fb28109d458`。
- 源码证据：原仓库 `03_DUT与源码锁定/evidence/stage03_source_manifest.json`。
- Bin identity 来源：原仓库 `06_覆盖数据转换/evidence/bin_manifest.json` 与 `coverage_bin_by_run.csv`。
- 固定 identity 列表：`canonical_bin_ids.txt`；来源 hash 与范围统计：`canonical_bin_catalog.json`。
- 重新提取：提供原始两个 stage06 文件后运行 `python tools/import_bin_catalog.py --csv <coverage_bin_by_run.csv> --manifest <bin_manifest.json>`。导入器验证 CSV SHA-256、4507 列数量及唯一性，只读取表头，不复制历史 run vectors。
- `bin_definitions.v1.json` 是从与固定 OpenTitan revision 匹配的 `coverage_manifest.v1.json` 派生的定义参考，只保留 bin 标签、区间、cross 成员和源码位置，不含 run 命中数。它核验了 4,507 个类型定义、6 组自动 bin 区间和 3 个 cross 笛卡尔积；160 个数组 bin 仍缺少各自边界，且旧 canonical 列只有部分直接标签匹配。使用 `python tools/import_bin_definitions.py --manifest <coverage_manifest.v1.json>` 可重建该文件。
- 迁移路线：本项目 `docs/migration-map.md`。

需要时按固定 revision 获取源码，不在新仓库 vendoring 整个 OpenTitan tree。
