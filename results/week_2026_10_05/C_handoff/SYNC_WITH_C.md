# B → C：周计划同步内容

使用现有 Drive data_v0，采用无独立训练 cohort 时的内部时间切分。共有 58 件分类资格样本，32 件训练、25 件测试、1 件时间边界排除（13001081）。训练观察期截止 2013-12-31；训练标签必须在该日期前可得，测试 cutoff 必须晚于该日期。A 家族分组和已有本地 PatEx 家族图均检查了跨集隔离。

## C 的统一 ID

- occurrence：classification_test_ids.csv 的 25 件（正 17、负 8）；对应 B 的 Majority/LR 结果。不能在全部 58 件上评分后直接与 B 的 25 件分数比较。
- OA 生成：generation_test_ids.csv 的 17 件，是上述测试集的 CTNF/CTFR 正例且有生成资格的子集。这个范围用于本次统一内部试跑；不是宣称周计划规定必须与分类同一数量。A 全部 37 件生成资格仍保留，但如另做全 37 件实验，需独立列 N 和范围。
- 三件试点仅调试，不计入分数。restriction/other 14572445 不进入二分类；13001081 的标签 2014-01-15 才可得，作为时间边界例排除。

## 输入与概率

只从 A 的 rounds.json 的 input_doc_ids 组装 cutoff 前 history；不能读取后续文书、target_doc_id 正文、真实 occurrence 或 label_available_date 来预测。gold 文件只用于评分，禁止传入模型。无 gold state。OA 用 native_text_path；其他用 text_clean；需要修改标记的 A1 claims 用 A 的最终 reviewed claims_markup/<stem>.txt。先核对文书清单和 cutoff，不能依据“文书在目录中”就当作输入。

固定一个可用模型和 prompt，输出 0–1 p_second_oa。保存 sample_id 和逐件概率。正类是 CTNF/CTFR 文书事件，负类 NOA，阈值 0.5；F1 为正类 F1，Brier 按概率计算。14723918 虽 CTFR 但未实际驳回 claims，仍按文书类型标正类，报告中不要把 occurrence=1 全称为实质再驳回。

预测文件最少包含 sample_id,p_second_oa，覆盖全部 25 件，不能静默省略失败。JSON 最多重试一次，保留失败原输出。固定模型实际版本、prompt、temperature、token 限制、文书输入 ID、截断规则、耗时和费用。

## C 尚需完成

1. 在 25 件上运行 LLM zero-shot occurrence，交付概率与完整运行记录，由 B 用现有 pilot score 统一评分，补齐第三行。
2. 在 17 件生成测试子集上运行 G0 复制 O1、G1 zero-shot、G2 同模型一次调用先列 claim/ground/evidence 对应再生成 OA，缓存原始输出。
3. 全文 ROUGE-1/L、METEOR；去模板实质指标若未完成记 pending。Judge 保留 disposition/grounds/evidence/reasoning/overall，至少报 grounds/evidence/overall，标为未校准 pilot agreement；缺 evidence 全文标 unknown。
4. 人工检查 5 件，保留一个正确例和一个失败例；与 A 审计、B 分类表合并为一页汇报。

## B 已完成与后续

已完成 Majority/LR、逐件概率、Acc/F1/Brier、切分与家族检查、A 标签一致性检查。当前LR为LR-reply：两个时间间隔，加A1 remarks长度、claims修改/新增标记及取消状态标记，共5个特征；训练内拟合中位数和缩放；LR C=1/lbfgs/max_iter=1000/seed=42。

Majority：N25、Acc0.68、F1=0.8095、Brier0.220625。
LR-reply（当前主展示基线）：N25、Acc0.64、F1=0.780488、Brier0.264450。
LR-time和LR-content保留为补充结果。LR-reply仍标为查看原测试结果后新增的探索版本；当前选择基于回复信息与任务匹配度，不声称预先固定或可靠提升。
本次只更新B模型展示，C的25件测试ID、cutoff、阈值及输入规则不变。当前LR预测使用lr_reply_predictions.csv；lr_predictions.csv为原LR-time历史文件，勿混用。

B 的正式三方法表需等 C 的 LLM 输出；目前不应写三方法公平比较已完成。本次为内部小样本时间留出，不是全部 58 件共同 benchmark 结果。用户明确不做 related work，本次不列 PatRe/PANORAMA 为待办；大 cohort 是可选补充，不是本周必交。

评分入口：
```sh
cd /path/to/ProsecutionBench
export PYTHONPATH="$PWD/src"
.venv/bin/python -m prosecution_data.pilot score --labels results/week_2026_10_05/C_handoff/classification_gold_for_scoring_only.csv --predictions /path/to/llm_predictions.csv --output /path/to/llm_metrics.json
```

此交接包只包含标签、ID、基线预测及说明；C 从已有共享 Drive 获取文本，无需申请新 API key 下载 USPTO 文书。模型调用仍需 C 现有模型接口。
