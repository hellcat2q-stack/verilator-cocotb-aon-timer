# 来源索引

- OpenTitan：lowRISC/OpenTitan revision `9f20940d494a223cc950a5b98f748fb28109d458`。
- 源码证据：原仓库 `03_DUT与源码锁定/evidence/stage03_source_manifest.json`。
- Bin identity 来源：原仓库 `06_覆盖数据转换/evidence/bin_manifest.json` 与 `coverage_bin_by_run.csv`。
- 固定 identity 列表：`canonical_bin_ids.txt`；来源 hash 与范围统计：`canonical_bin_catalog.json`。
- 重新提取：提供原始两个 stage06 文件后运行 `python tools/import_bin_catalog.py --csv <coverage_bin_by_run.csv> --manifest <bin_manifest.json>`。导入器验证 CSV SHA-256、4507 列数量及唯一性，只读取表头，不复制历史 run vectors。
- 迁移路线：本项目 `docs/migration-map.md`。

需要时按固定 revision 获取源码，不在新仓库 vendoring 整个 OpenTitan tree。
