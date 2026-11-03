# B Examiner Prediction 第二阶段结果分析

结论：匹配审查员画像在两模型上均提高 Occ. AUROC，且优于 mismatched 对照。Type 的增益在 GPT 上有较明确支持，在 Qwen 上区间仍跨 0。Grnd. 未显示稳定增益，不能表述为 RAG 全面提升预测。

## 样本与验证

两模型各 own/mismatched 100/100 最终成功，共 400 条新 core 结果；复用 200 条无画像结果。相同输入、固定 state、模型版本、配置、请求与画像哈希已经由原比较入口复核。重新执行 family 配对 bootstrap 1,000 次，seed=20261010；全部区间有 1,000 个有效重采样。本次离线分析未发起新 API 调用。

Occ./Type：99 件；排除 14572445_t1（restriction）。Grnd.：62 件；保留缺标签和 14012315_t1 的 112d 类别冲突，未知不当空集合。标签仍是 automatic_unreviewed。artunit 未运行。

## 主结果

| 模型 | 条件 | Occ. AUROC | Type macro-F1 | Grnd. micro-F1 |
|---|---|---:|---:|---:|
| GPT-5-mini | no_profile | 0.5481 | 0.1803 | 0.2242 |
| GPT-5-mini | own | 0.7507 | 0.4404 | 0.1803 |
| GPT-5-mini | mismatched | 0.4786 | 0.3006 | 0.1141 |
| Qwen3.6-27B | no_profile | 0.6495 | 0.4081 | 0.2944 |
| Qwen3.6-27B | own | 0.7857 | 0.4690 | 0.3321 |
| Qwen3.6-27B | mismatched | 0.6519 | 0.4084 | 0.2947 |

## 配对增量与95%区间

Δ按右侧条件减左侧条件计算；区间为家族配对 percentile bootstrap，未作多重比较校正。

| 模型 | 比较 | 指标 | Δ | 95% CI |
|---|---|---|---:|---|
| GPT-5-mini | own_minus_no_profile | Occ | +0.2026 | [+0.0720, +0.3210] |
| GPT-5-mini | own_minus_no_profile | Type | +0.2600 | [+0.1685, +0.3563] |
| GPT-5-mini | own_minus_no_profile | Grnd | -0.0439 | [-0.1005, +0.0084] |
| GPT-5-mini | mismatched_minus_no_profile | Occ | -0.0694 | [-0.2200, +0.0730] |
| GPT-5-mini | mismatched_minus_no_profile | Type | +0.1203 | [+0.0216, +0.2140] |
| GPT-5-mini | mismatched_minus_no_profile | Grnd | -0.1101 | [-0.1732, -0.0547] |
| GPT-5-mini | own_minus_mismatched | Occ | +0.2720 | [+0.1240, +0.4204] |
| GPT-5-mini | own_minus_mismatched | Type | +0.1398 | [+0.0503, +0.2362] |
| GPT-5-mini | own_minus_mismatched | Grnd | +0.0662 | [-0.0109, +0.1482] |
| Qwen3.6-27B | own_minus_no_profile | Occ | +0.1362 | [+0.0301, +0.2493] |
| Qwen3.6-27B | own_minus_no_profile | Type | +0.0609 | [-0.0019, +0.1197] |
| Qwen3.6-27B | own_minus_no_profile | Grnd | +0.0377 | [-0.0380, +0.1108] |
| Qwen3.6-27B | mismatched_minus_no_profile | Occ | +0.0024 | [-0.1096, +0.1246] |
| Qwen3.6-27B | mismatched_minus_no_profile | Type | +0.0003 | [-0.0644, +0.0742] |
| Qwen3.6-27B | mismatched_minus_no_profile | Grnd | +0.0004 | [-0.0783, +0.0888] |
| Qwen3.6-27B | own_minus_mismatched | Occ | +0.1338 | [+0.0259, +0.2550] |
| Qwen3.6-27B | own_minus_mismatched | Type | +0.0606 | [-0.0036, +0.1283] |
| Qwen3.6-27B | own_minus_mismatched | Grnd | +0.0373 | [-0.0544, +0.1299] |

## 解释

1. Occ. 是最一致的正向结果。own−baseline：GPT +0.2026 [0.0720,0.3210]，Qwen +0.1362 [0.0301,0.2493]；own−mismatched 也分别为 +0.2720 与 +0.1338，区间均高于0。mismatched−baseline 的 Occ. 区间均跨0。结果支持匹配历史信息有用，不能仅用“多了一段文字”解释；但没有拆分统计与案例组件，不能归因于检索案例单独起效或证明纯身份因果效应。

2. Type 的 GPT 增益主要伴随类别偏好改变。CTFR 命中从7/59变为51/59，NOA 从6/36变为17/36；但4件CTNF在own条件下全部未命中。Qwen own 的 NOA 命中16/36→23/36，CTFR为46/59→47/59，同样没有命中CTNF。少数类样本很少，三类能力仍不均衡。GPT mismatched 的 Type 也上升，故不能把GPT全部Type增益视为正确审查员匹配的独有效果；own−mismatched仍为正且区间不跨0。

3. Grnd. 是主要短板。GPT own 的TP 138→106、FN 885→917，预测pair总数208→153；precision 0.6635→0.6928，recall 0.1349→0.1036。表现为输出更少、漏检更多，micro-F1下降0.0439，但该下降区间仍跨0。Qwen own 的TP 199→221、FP 130→87，precision 0.6049→0.7175，recall 0.1945→0.2160，点估计改善但区间跨0。不能声称Grnd.已有稳定提升。

4. 校准辅助结果也改善：own 的Brier（越低越好）GPT 0.2556→0.1956，Qwen 0.2341→0.1888；这里仅作描述，没有另行计算Brier差值区间。Occ.提升指下一CTNF/CTFR文书事件的概率排序，不能解释为实质驳回或claim-ground准确性的同等提升。

## 运行完成情况

两模型四个新预测条件均最终成功100/100。历史失败尝试已保留：GPT own与mismatched各2次，Qwen own 15次、mismatched 28次；最终比较没有因调用失败丢失样本。

## 结论边界

适合的表述：在固定test_core及冻结设置下，匹配审查员历史画像在两个模型上均提高下一Office Action事件的区分能力；通知类型和claim-ground预测的获益依赖模型及指标。

不能据此宣称：所有任务均提升、两个模型增益幅度差异已显著、检索组件单独有效，或法律语义准确性已验证。这里只做样本配对区间，未评估多次模型运行的随机波动；家族分组受A提供的覆盖范围限制。统计与检索实例混合、实际k略有差别、ground标签仍为自动草稿。

后续分析优先核对Grnd.漏检和CTNF少数类错误；若以后新增统计-only或案例-only消融，应作为独立预先声明实验，保留本次冻结结果，不根据当前test效果修改提示。

主要评分依据：comparison.json。原始预测、逐案评分及独立运行记录继续保留。
