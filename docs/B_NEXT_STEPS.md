# B：清单到位前可完成的准备

新增模块 `prosecution_data.pilot` 不需要额外依赖。

## 候选下一事件

输入 seeds CSV 至少包含 `sample_id,app_id,cutoff`。cutoff 必须由文书核验提供；程序不自动宣称找到完整 A1。

```bash
cd <repository-root>
export PYTHONPATH="$PWD/src"
.venv/bin/python -m prosecution_data.pilot candidates \
  --seeds data/patex_2022/processed/labels.csv \
  --transactions data/patex_2022/raw_csv/transactions.csv \
  --snapshot YYYY-MM-DD \
  --output data/patex_2022/processed/candidates.csv
```

将 YYYY-MM-DD 替换为经过确认的源数据快照日期，不是下载日期。命令扫描约 12 GB 文件；只保存目标申请的原始交易行，写入相邻 `.transactions.csv` 审计文件。首次测试也可以使用小的交易 CSV。

处理记录不会替代寄出日期；NINA 等已列出的其他通知和程序变化不会被跳过。同日相关事件标 uncertain。没有事件时标 censored_or_missing，不能仅凭缺少交易确认删失。事件白名单需持续与源文书核对：未知代码保留在交易审计中，可能需要增加映射。

输出全部标 metadata_candidate、eligible_cls=False，不能自动覆盖正式 labels.csv。逐件将结果与已核验标签比较，特别检查日期、NINA、重复处理/寄出记录。该命令不执行 O1/A1 文书分组、family 构建、训练切分或 LR。

## 统一分类评分

每个方法单独提供 CSV：`sample_id,p_second_oa`。不要混入 supplementary 样例；不要省略 API 失败的 ID，应先报告失败并明确共同评分规则。

```bash
.venv/bin/python -m prosecution_data.pilot score \
  --labels data/patex_2022/processed/labels.csv \
  --predictions /path/to/method_predictions.csv \
  --output /path/to/method_metrics.json
```

输出 N、Acc、正类 F1、Brier、正负例数量。固定阈值 0.5；拒绝空评测集、重复/缺失/额外 ID、非有限概率和越界概率。重复输出文件会被拒绝，不静默覆盖。

三件样例只验证流程；不得把本阶段的合成预测或三件样例评分作为模型效果。

## 清单到位后的顺序

1. A/B 固定共同 ID 和源数据快照。
2. 从完整交易记录导出候选，文书核对后更新 labels。
3. 核验 utility 与技术领域抽样、family 与训练标签可得日期。
4. 固定时间及 family 切分；禁止未知 family 用于宣称 family-disjoint。
5. 在训练集拟合预处理、Majority prior 与 LR，输出每件概率。
6. C 使用同一 test IDs；每个方法用本模块统一评分。

Majority/LR 训练模块已补充：参见 [BASELINES.md](BASELINES.md)。
