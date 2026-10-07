# Family 与训练候选池准备

运行模块：`prosecution_data.cohort`。只生成待核验候选，不创建正式训练集、切分或模型分数。

```bash
cd <repository-root>
export PYTHONPATH="$PWD/src"
.venv/bin/python -m prosecution_data.cohort \
  --raw-dir data/patex_2022/raw_csv \
  --output-dir data/patex_2022/processed/cohort_prep_1000 \
  --limit 1000 --seed 42 \
  --observation-end 2022-06-23 \
  --pilot-labels data/patex_2022/processed/labels.csv
```

上述目录为首次实跑目录，重复运行须换一个新目录。2022-06-23 是本地交易表实测最大事件日，用作分析上界，不是已验证源快照。正式源版本仍待核对。

## 产物

- `family_map.csv`：1000 件候选加三件试点的 app_id、family_id、组件节点数和解析状态。
- `selected_transactions.csv`：目标申请的全部原始交易行，含处理、寄出、行政及未知事件；未删改原始数据。
- `training_candidates.csv`：候选 O1 寄出日期、回复日期、下一事件及排除原因。全部 eligible_cls=False、label_status=metadata_candidate。
- `audit.json`：全表扫描数、过滤数、continuity 非法行数、候选分类与实际耗时。

## Family 规则

扫描父、子两张表的全部有效关系，不只扫描候选申请；保留范围外节点和可识别的 PCT 节点。连通分量按所有节点中的最小规范化编号赋 ID，因此不随本次抽样改变。按字符串读取数字申请号，保留前导零；不能猜测科学计数法或未知格式。

singleton_in_local_continuity 只表示当前两张表未提供连接，不保证全球范围完全无同族。PCT 桥接可使 family 比仅按美国直接延续关系更保守；这是避免泄漏的分组方案，正式发表时应说明定义。未识别关系有审计计数，非零时必须进一步核查。

## 候选池规则

从申请年份 2008-2015、Utility、存在公开或专利编号的记录中，用 seed+app_id 的 SHA256 排名取前 1000 件，排除三件试点 ID。不是技术中心分层的共同样本，也没有要求最终授权。

从最早 MCTNF/MCTFR 定位 O1，寻找其后的第一候选回复 A.../A/RR/A.NE/AAF.。回复前先出现下一 OA、其他相关通知或程序变化时，不跨越该事件寻找回复。仍需要文书核对 O1 是否最早、回复是否完整、事件对应及日期。白名单未覆盖的代码必须从原交易审计核查。

回复后下一通知的处理沿用主任务口径：CTNF/CTFR 对 NOA；NINA 等记 other；RCE/appeal 等记 out_of_scope；无后续事件保持 censored_or_missing，不默认负类。补正后的案例不得混入第一回复主任务。

## A 清单到位后

1. 将共同样本 ID 纳入同一个全局 continuity 图查询，不能另外用子集重命名 family。
2. 排除与共同测试样本同 family 的训练候选。
3. 固定训练观察期；训练标签必须在观察期内可得，所有测试 cutoff 更晚。
4. 核验训练候选的回复、标签来源和任务资格。候选字段不可自动升级为 document_verified。
5. 形成正式 labels/split/features，调用 BASELINES.md 的训练命令。

Family 与源快照未确认、候选标签未核验时，不运行正式效果评估。

## Continuity 异常审计（2026-10-06）

完整清单及结果见 processed/cohort_prep_1000/family_audit。216 条 rejected edges：186 unrecognized_pct、25 missing_relative、1 pct_separator_variant、4 unrecognized_relative。重建图后，1003 个目标申请（1000 候选＋3 试点）中没有已知组件被这些 rejected edges 的可识别端点触及；family IDs 与原输出完全一致。未自动改写编号。

这不是全球 family 完整性保证：无法识别端点可能隐含额外连接，源快照问题也尚未解决。A 的新样本需要独立映射并再次检查训练/测试 family 重叠。

source_verification_queue_12.csv 从两个候选标签中各取事件日期最早的 6 件，用来核验标签规则。人为平衡且按日期排序，仅供标注审计，不是正式训练/测试抽样；不能用它报告泛化分数。所需 O1、A1 和下一通知日期已列出，doc ID/完整内容仍待源文书核对。
