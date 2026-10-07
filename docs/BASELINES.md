# B 的分类基线运行说明

该版本固定比较 Majority prior 和 Logistic Regression。使用显式 train/test 清单，不自行抽样或利用测试结果调参。真实三件仅核验标签与特征；`synthetic_smoke` 下的分数仅证明代码能跑通。

## 依赖与启动

```bash
cd <repository-root>
export PYTHONPATH="$PWD/src"
.venv/bin/python -m pip install -e '.[baseline]'
```

源码直接运行无需重新安装项目；baseline extra 声明 scikit-learn，当前虚拟环境已安装。项目曾从 Documents 搬至 Desktop，使用 `python -m` 避免旧入口脚本的路径问题。

## 输入

1. `labels.csv`：至少 sample_id、app_id、family_id、cutoff、label_available_date、occurrence、eligible_cls、label_status、scope。只评 eligible_cls=true、label_status=document_verified、scope=main。family 的图构建与来源需要独立核验，非空字符串本身不能证明 family 正确。
2. `split_manifest.csv`：sample_id、family_id、cutoff、split。只接受 train/test，覆盖全部 eligible IDs；不能含 excluded/supplementary ID。
3. `features.csv`：sample_id、days_filing_to_o1、days_o1_to_reply。禁止添加其他列。空值使用训练集的中位数填补。

训练观察期结束日期必须早于全部测试 cutoff，且训练标签在该日期前已可得。同族及同申请不能跨集，split 中的 cutoff 与 family 必须和标签完全一致。LR 训练必须包含两个类别。测试单类别仍报告 Acc/F1/Brier，但不能支持稳定的效果结论。

## 生成日期间隔特征

```bash
.venv/bin/python -m prosecution_data.baselines features \
  --labels data/patex_2022/processed/labels.csv \
  --application-data data/patex_2022/raw_csv/application_data.csv \
  --output data/patex_2022/processed/features.csv
```

该命令扫描申请表，只保留 eligible 样例的 filing_date，使用 labels 中已核验的 o1_mail_date 和 cutoff。缺失 filing_date 保留为空；日期倒置报错。输出不包含 examiner、art unit、当前状态、最终授权日期或未来耗时。

## 训练与评分

先固定训练和测试样本，并填写 family。当前三件标签的 family 仍未核验，不能直接跑正式训练。

```bash
.venv/bin/python -m prosecution_data.baselines train \
  --labels /path/to/combined_verified_labels.csv \
  --split /path/to/split_manifest.csv \
  --features /path/to/features.csv \
  --train-observation-end YYYY-MM-DD \
  --output-dir data/patex_2022/runs/run_001
```

替换输入文件与训练观察期日期。使用不存在的新目录；不覆盖旧结果。

输出：
- majority_predictions.csv、lr_predictions.csv：相同测试 sample_id 和正类概率，可直接交给 pilot score。
- metrics.json：每种方法的 N、Acc、正类 F1、Brier。
- run_config.json：输入 SHA256、train/test IDs、类别数量、预处理统计、特征白名单、版本与参数。
- lr_model.joblib：训练后的完整预处理及 LR 模型。不要加载不可信来源的模型文件。

Majority 的概率为训练集正类比例，统一阈值 0.5；平票时预测 1。LR 固定 C=1、lbfgs、max_iter=1000，无类别重加权。填补和缩放仅在训练集拟合，收敛失败会报错。

实现参考：[scikit-learn LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) 和 [SimpleImputer](https://scikit-learn.org/stable/modules/generated/sklearn.impute.SimpleImputer.html)。

## 当前待办

- A 的共同清单与文书核验。
- 真实训练 cohort、family 构建与固定时间切分。
- 本地交易文件与官方 release 描述的来源差异。
- 扩充正式 labels 后运行，C 复用相同 test IDs。

## Current presentation update (2026-10-07)

LR-reply is now the structured baseline in the main presentation table, by explicit user decision to include reply information. LR-time and LR-content remain supplementary. LR-reply is still exploratory because it was proposed after inspecting the original test scores. See results/week_2026_10_05/primary_baseline.json and docs/B_BRIEFING_EN.md. Original lr_predictions.csv and root metrics.json describe LR-time, not the current baseline. Reproduce the current LR with python scripts/reproduce_lr_reply.py.
