# GPT teammate handoff — BGE-M3 shared profiles

本轮分工：B 跑 Qwen，队友跑 GPT。这里提供原有预测代码、冻结系统提示、测试和交接步骤。**本目录不是新实验完成记录；未启动新的 GPT/Qwen API 调用。**

## 先看这里

- 本轮画像 release：`B_shared_BGE_M3_dense_v1_2026_11_05`。
- 使用相同的 100 件基础输入和 `no_profile / own / mismatched` 条件，不做 artunit；mismatched 直接用交接包的既定配对。
- GPT 版本 `gpt-5-mini-2025-08-07`，low reasoning，不传 temperature，JSON object；初始输出上限 8192，截断重试上限 16384。保留原 runner 的两次内容尝试上限、显式失败和成功缓存规则。
- **`code/b_phase2_prediction.py` 是旧 TF-IDF 入口的原样参考副本。不要直接运行它的 prepare/offline/dev/core/compare 命令。** 它仍绑定旧 release、旧路径、旧 gate 和两模型比较。安全复用的是其画像拼接、基线审计、评分资格和 bootstrap 函数；新版路径必须显式传入或重新绑定。
- 本公开目录不含完整画像、原文、固定基础输入、gold、旧 API 结果、审阅材料、实际 endpoint/deployment 或凭据。下面团队文件必须另行接收，不能从公开仓库下载到。

## 现有代码怎么复用

| 文件 | 用途 |
|---|---|
| `code/b_prediction.py` | GPT runner：`run`、`azure_transport`、`validate_prediction`、`score`，包含 request_hash、缓存、原始响应、重试与用量记录。原样复制，保留实现哈希 |
| `code/b_run_paced.py` | `paced_transport`；默认请求间隔 65 秒，首次请求也等待；不额外叠加传输重试 |
| `code/b_phase2_prediction.py` | `append_profile`、`audit_baseline`、`eligibility`、`paired_comparison` 参考实现。完整入口仅适用于上一版 |
| `code/b_qwen.py` | 上述参考模块的导入依赖，不要求 GPT 队友运行 Qwen；副本中旧 Qwen CLI 默认服务地址已替换为 example.invalid |
| `prompts/examiner_prediction.FROZEN.txt` | 原冻结系统提示；不根据测试输出修改 |
| `tests/` | 原有纯合成/临时目录测试，仅调整导入路径指向 code/；不需要团队私有材料，不调用真实 API |
| `SOURCE_MANIFEST_SHA256.json` | 本次上传文件与原本地源文件的 SHA256 对应 |

不需要 embedding 模型、GPU 或向量缓存来运行预测；直接读取已经审核并封存的最终 `profile_text`。

## 团队渠道另传的文件

以下为 B 原项目根目录下的相对路径。建议接收后保留原结构；把该根目录称为 `TEAM_ROOT`。

| 文件 | 用途 |
|---|---|
| `week10_11/B/prepared/inputs/prediction_core.jsonl` | 原 100 件基础输入，已包含固定预测 state；不要重新生成 state |
| `week10_11/B/prepared_dev/inputs/prediction_dev.jsonl` | 原 3 件 dev 输入，不评分 |
| `week10_11/B/frozen_setting.json` | 实际 endpoint/deployment 和固定模型配置；不含 API key，仍走团队渠道 |
| `week10_11/B/outputs/core/examiner_prediction.jsonl` | 旧 GPT 100 件 no_profile 结果，严格核验后复用 |
| `week10_11/B/prepared/gold/action_type_gold.core.draft.csv` | Occ./Type 标签，仅用于评分 |
| `week10_11/B/prepared/gold/claim_ground_gold.core.draft.jsonl` | 原始 ground 标签，核对用 |
| `week10_11/B/outputs/core/claim_ground_gold.scoring.draft.jsonl` | 实际评分 ground 标签 |
| `week10_11/B/outputs/core/gold_taxonomy_issues.json` | 已记录的 taxonomy 例外 |
| `week10_11/shared/data_package/data_v1_share/sample_manifest.csv` | 固定样本、cutoff、family_id、split |
| `B_shared_BGE_M3_dense_v1_2026_11_05_TEAM_ONLY.zip` | 已交接的最终共享画像包 |

画像 ZIP SHA256：`ff3db404a413b1f1d74b3f5c1b2b4c198d9ab87ef28196cfc7c32c3496e38917`。
解压后核验 `HANDOFF_MANIFEST_SHA256.json` 中所有列出的文件。只用最终 `candidate_profiles/{own,mismatched}/*.json`；`review/` 展示的是剔除前候选，不能从中重建输入。

不要把 `TEAM_ROOT`、解压画像或运行目录放进公开仓库。不要共享 API key。

## 安装与离线代码检查

在本交接目录运行（Python 3.11+；另保留实际 Python/依赖版本记录）：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q -p no:cacheprovider tests
```

测试不会验证真实 endpoint、私有数据或新画像完整实验。依赖范围来自原项目，不是声称完整环境已锁定；正式运行请另存 `pip freeze`。

## 准备新预测输入

新实验使用独立目录，例如公开 checkout 之外的 `PRIVATE_RUN/inputs`、`PRIVATE_RUN/runs/gpt/{dev,own,mismatched}`。不要写回旧 `phase2_prediction_v4_reviewed` 或封存画像目录。

可导入原拼接函数：

```python
import sys
sys.path.insert(0, 'code')
import b_phase2_prediction as phase2
import b_prediction as bp
```

准备逻辑：

1. 读取固定 `prediction_core.jsonl`，检查恰好 100 个唯一 sample_id；与 A manifest 的 test_core 集合一致。
2. 读取最终画像 manifest，校验每个画像文件 SHA1、`profile_text_sha1`、card_sha1 和 cutoff；使用画像 `prediction_sample_id` 对应预测 `sample_id`。画像 manifest 的申请 ID 不带 `_t1`，不要盲目拼接或混用。
3. 两种条件分别按同一个基础输入顺序构建。`profile_provenance` 至少记录 release_id、包内相对 profile_path、profile_sha1、profile_text_sha1、card_sha1、retrieved_k；两人使用相同字段和值，避免仅因本机绝对路径不同造成输入文件哈希不一致。
4. 调用 `phase2.append_profile(base, profile, provenance, variant)`。它保留基础消息和 state，只追加 `\n\nEXAMINER PROFILE (past, other families):\n` 与最终 `profile_text`。
5. 不把 gold、控制标签、审核意见、来源原文区和身份哈希加进消息；这些留在追溯记录。
6. 保存 `own.jsonl`、`mismatched.jsonl` 及各文件 SHA256；双方在 API 调用前核对这些文件哈希。记录每份最终输入的基础消息、state、画像正文和完整请求哈希。
7. k=0 的统计画像仍保留；不按新检索效果删样本，不重新配对 mismatched，不补回已撤下案例。

保留原模型可见拼接格式，避免自行给 GPT/Qwen 分别改写、概括或裁剪画像。

## 核验并复用 no_profile

`phase2.audit_baseline('gpt', core_rows)` 可复用，但它通过原全局路径读取文件。若在本交接目录调用，需要先显式重绑定 `phase2.PROMPT`，并将 `phase2.frozen_path`、`phase2.baseline_path` 指向团队接收的原文件；`phase2.adapter_hash` 仍应计算本次原样复制的 `b_prediction.py`。

审计必须检查 100 件成功结果、原 base message/state/input/prompt/request hash、模型、完整配置与原适配器哈希。若不能通过就不能声称基线可复用。更换 endpoint/deployment 也属于配置变化，需记录并处理相应基线；不能只凭模型名称一致就复用。

旧 TF-IDF own/mismatched 输出仅作旧设置对照，不能充当这轮新版画像输出。

## GPT 调用示例

以下是如何调用已有 runner 的示例，**不是一个已验证的新实验总入口**。`input_path` 与 `output_dir` 必须指向上一步生成并核验的新文件/新目录，config 从团队私有 `frozen_setting.json` 读取。运行者在自己终端设置 `AZURE_OPENAI_API_KEY`，不写入代码或仓库。

```python
import json
from pathlib import Path
import sys
sys.path.insert(0, 'code')
import b_prediction as bp
from b_run_paced import paced_transport

config = json.loads(private_frozen_setting.read_text())['config']
summary = bp.run(
    inputs=input_path,
    prompt=Path('prompts/examiner_prediction.FROZEN.txt'),
    output=output_dir,
    config=config,
    transport=paced_transport(bp.azure_transport(config), interval=65),
)
```

顺序：

1. 先做离线格式/哈希检查和合成响应测试。
2. 在 3 件固定 dev 上跑真实 API，不评分、不调测试提示。dev 的历史应明确为空/合成占位，不能套用测试案件画像。可重绑定 `phase2.DEV` 后复用 `phase2.dev_rows()` 构建。
3. 检查 dev 3/3 成功、返回模型版本、概率/JSON/claim-ground、重试和保存情况，保存绑定当前输入/提示/配置/代码哈希的独立 dev 检查记录。旧 gate 不能证明新入口已验证。
4. 通过后分别运行 own、mismatched，各 100 件。中断后在同一输入、配置、目录续跑，成功缓存自动复用；不要同目录启动两个进程。
5. 每次调用前保存 request_hash 与画像 provenance 的关联。原 `bp.run()` 不会自动输出旧 wrapper 的 `request_provenance.jsonl`，因此必须另外保存该对应关系，并核对输出 request_hash。完整请求哈希使用原 `bp.digest({'messages': ..., 'config': 完整configuration, 'provenance': 输入行除user_message外字段})`；完整 configuration 的构造与 `bp.run` 保持一致，不只用 frozen config 的四个字段。

没有超长输入截断规则时禁止自行静默裁剪；遇到上下文限制应保留失败和输入哈希并协同处理。不要通过换提示、换 state 或删样本解决格式失败。

## 评分与两人合并

- `bp.score()` 负责 Occ. AUROC、固定三类 Type macro-F1、claim-ground micro-F1。`b_prediction.py score --types ... --grounds ... --predictions ... --output ...` 可用于单条件评分；grounds 参数应使用评分副本。
- Occ./Type 完整有效 N=99；Grnd. N=62。restriction `14572445_t1` 排除；`14012315_t1` 的 112d 沿用整案 ground 未知，不映射、不当空集合。标签仍是自动草稿，不能宣称人工 gold。
- 用三条件共同成功样本作为同模型的共同队列，然后按每项资格过滤；显式列失败和缺失 ID，覆盖不足标 partial。
- `phase2.paired_comparison(gold, left_index, right_index, n_boot=1000)`：按 family_id 配对 bootstrap，seed=20261010，95% percentile CI，delta=right−left。gold 中须有 sample_id、family_id、eligible、next_type、occurrence、pairs。
- 报告 own−no_profile、mismatched−no_profile、own−mismatched；bootstrap undefined 次数保留。
- GPT 与 Qwen 分别先完成模型内比较。直接跨模型比较时另核对共同成功样本，不能把不同样本分母的差值当成严格配对结果。
- 结果主表不放 token/费用；用量、长度、重试单独留档。两模型保留原各自推理设置，不声称严格预算匹配。

## 回传给 B

回传整个私有新运行目录，至少包含：

- 运行配置、代码/环境版本、release ID、最终输入与提示哈希、基线复用审计、dev 记录；
- 每次请求与最终画像的 provenance 对应、sample_id/condition/request_hash；
- `examiner_prediction.jsonl`、`examiner_prediction.csv`、`claim_ground_predictions.jsonl`、`run_summary.json`（以实际 runner 输出为准）；
- `raw/`、`cache/`、全部 attempt 的 `usage_log.jsonl`，失败原因和重试；
- 单条件指标、三条件共同队列、差值/CI、排除/失败 ID。

如自行生成 `examiner_prediction.with_provenance.jsonl`，附带回传；不要只交汇总分数。任何 raw/inputs/gold/画像文件都不要提交到这个公开仓库。

## 当前交接边界

本包交付可复用的原代码与明确操作规则，没有伪装成已经完成的新版自动入口。固定输入、画像接入、新版 provenance/dev 检查与 GPT 单模型比较入口需要按上述规则在团队私有工作区准备并验证；完成后才能启动整批。共享画像只完成检索交付，不代表预测效果已被验证。
