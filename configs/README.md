# 配置目录

登记源码 revision、工具版本、测试池、seed、预算、worker 和运行协议。正式运行前冻结参数；变化时建立新 schema 或 run ID。

阶段 05 的 `stage05-test-pool.json` 是唯一刺激参数源；`stage05-freeze.json` 保存其规范化文本 SHA-256 和固定源码 revision。改动测试池参数时，必须新建 pool/freeze ID 并重新执行全套校验，不能静默覆盖现有冻结协议。

`coverage_schema.json` 中的 `sample_site_mapping` 登记已接入 raw trace 的采样调用点与未接入项目；只有 `status: COMPLETE`、`complete: true` 且 `unmapped` 为空时，Stage 08 preflight 才会通过采样完整性门。
