# 场景评测

需求文档规划的 120 条场景尚未创建；当前已有测试位于 `tests/`。

后续布局：`datasets/dev.jsonl`、`datasets/test.jsonl`、`fixtures/`、`scorers/`、`reports/`。
开发集用于调参，保留测试集冻结；不把测试集资料加入在线知识库。
真实模型评测与无密钥的 CI 基础测试分别报告，不能把模拟供应商结果当成任务成功率。
