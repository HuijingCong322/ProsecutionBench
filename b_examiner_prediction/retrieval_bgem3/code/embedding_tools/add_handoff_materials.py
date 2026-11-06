import sys,json,shutil,hashlib,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from b_embedding_profiles import *
from b_embedding_handoff import DEST,verify_final_files
from b_sentence_embedding import VectorCache
root=DEFAULT;dest=DEST
if (dest/'HANDOFF_MANIFEST_SHA256.json').exists():raise ValueError('Sealed snapshot is immutable')
verify_final_files(dest)
summary=json.loads((dest/'RELEASE_MANIFEST.json').read_text());contract=json.loads((dest/'embedding_contract.json').read_text());cache=VectorCache(contract['cache_root'],contract)
queries={r['sample_id']:r['technical'] for r in readjl(root/'queries.jsonl')};mapping={(r['sample_id'],r['variant'],r['episode']['episode_id']):r for r in readjl(root/'candidate_mapping.jsonl')}
examples=[];sections=[]
for sid in PRECHECK:
 q=queries[sid];v=cache.get(q['text']);record={'sample_id':sid,'cutoff':q['cutoff'],'encoder_actual_input':q['text'],'query_text_sha256':q['text_sha256'],'query_sources':[{k:x for k,x in src.items() if k!='text'} for src in q['fields'].values()],'actual_dense_output':{'dimension':len(v['vector']),'norm':math.sqrt(sum(x*x for x in v['vector'])),'first_12_values':v['vector'][:12],'cache_key':v['key'],'cache_checksum':v['checksum']},'model_id':contract['model_id'],'model_revision':contract['revision'],'variants':{}}
 sections.append(f'## {sid}\n\n目标技术文本（节选；完整输入见 actual_retrieval_input_output.json）：\n\n> '+q['text'][:700].replace('\n','\n> ')+'\n')
 for variant in ['own','mismatched','artunit']:
  raw=json.loads((root/'shared_candidate/candidate_profiles'/variant/f'{sid}.json').read_text());effective=json.loads((dest/'candidate_profiles'/variant/f'{sid}.json').read_text());kept={e['app_id'] for e in effective['retrieved_cases']};top=[]
  sections.append(f'### {variant}: 原始 k={raw["retrieved_k"]}；交接实际 k={effective["retrieved_k"]}\n\n| 原排名 | 历史申请 | cosine | 交接状态 |\n|---:|---|---:|---|')
  for e in raw['retrieved_cases']:
   tech=mapping[sid,variant,e['episode_id']]['technical'];top.append({'rank':e['rank'],'historical_app_id':e['app_id'],'family_id':e['family_root'],'episode_id':e['episode_id'],'similarity':e['similarity'],'technical_text':tech['text'],'technical_text_sha256':tech['text_sha256'],'source_paths':[x['path'] for x in tech['fields'].values()],'source_dates':[x['date'] for x in tech['fields'].values()],'included_in_shared_profile':e['app_id'] in kept})
   sections.append(f'| {e["rank"]} | {e["app_id"]} | {e["similarity"]:.6f} | '+('保留（有限定）' if e['app_id'] in kept else '相关性审核撤下；不补例')+' |')
  sections.append('')
  record['variants'][variant]={'raw_topk':top,'effective_retrieved_k':effective['retrieved_k'],'effective_profile_text_sha1':effective['profile_text_sha1'],'withheld_app_ids':effective['review_withheld_app_ids']}
 examples.append(record)
write_json(dest/'actual_retrieval_input_output.json',examples)
(dest/'DISPLAY_EXAMPLES.md').write_text('# 实际检索输入、输出与审核例子\n\n本文件展示预先固定的三案，不根据预测效果选例。cosine 不是相关性审核结论。完整来源、全部技术文本和实际 dense 输出预览保存在 JSON；向量全文留在可追溯的本地缓存。\n\n'+'\n'.join(sections)+'\n所有例子均来自同一冻结 BGE-M3 dense 配置；未发起 GPT/Qwen 预测。\n')
p=json.loads((dest/'candidate_profiles/own/13773735.json').read_text());(dest/'MODEL_VISIBLE_PROFILE_EXAMPLE.txt').write_text(p['profile_text'])
shutil.copy2(s.B/'prompts/examiner_prediction.FROZEN.txt',dest/'prompts/prediction_prompt_reference_UNCHANGED.txt')
code=dest/'code';code.mkdir()
for name in ['b_sentence_sources.py','b_sentence_embedding.py','b_embedding_profiles.py','b_embedding_review.py','b_embedding_handoff.py','b_embedding_cache_import.py','requirements.bgem3.lock.txt','EMBEDDING_SHARED_PROFILE_RUN.md']:
 shutil.copy2(s.B/name,code/name)
shutil.copytree(s.B/'embedding_tools',code/'embedding_tools',ignore=shutil.ignore_patterns('__pycache__'))
(code/'tests').mkdir()
for name in ['test_sentence_sources.py','test_sentence_embedding.py','test_embedding_profiles.py','test_embedding_review.py','test_embedding_handoff.py','test_embedding_cache_import.py']:shutil.copy2(s.B/'tests'/name,code/'tests'/name)
write_json(dest/'IMPLEMENTATION_FACTS.json',{'model_pooling':'CLS only, as pinned 1_Pooling/config.json','model_precision':'float16 on MPS; CLS transferred as float32','normalization_and_similarity_precision':'Python float64; JSON numbers','query_document_prefix':'none; only technical field labels','model_weights_packaged':False,'full_vector_cache_packaged':False,'cache_location_and_checksums':'embedding_contract.json + embedding_cache_manifest_all.csv','raw_source_flag_semantics':'source_flag_semantics.json','encoder_sha256_matches_contract':s.sha(s.B/'b_sentence_embedding.py','sha256')==contract['encoder_sha256'],'source_sha256_matches_contract':s.sha(s.B/'b_sentence_sources.py','sha256')==contract['source_code_sha256'],'code_copy_usage':'Code is a mirror of project week10_11/B; restore into that directory with shared data layout, or remap source roots before a separately versioned run.'})
text=f'''# BGE-M3 共享画像交接（本地／团队专用）

发布编号：{summary['release_id']}。本轮完成检索和共享画像；GPT/Qwen 新预测调用为 0，旧快照、统计卡、预测输入／提示／结果保持不变。

## 从哪里开始

- `candidate_profiles/{{own,mismatched,artunit}}/*.json`：全部 {summary['profiles']} 份交接画像。**模型只能接收 `profile_text`**；其余控制标签、审阅意见、身份哈希和来源材料留在模型消息外。
- `profile_manifest.csv`：新文件 SHA1、profile_text SHA1、D card_sha1、cutoff、实际 k、审核范围。
- `historical_links.csv`：sample_id、cutoff、variant、historical_app_id、family_id、episode_id、rank、rendered_rank、similarity、模型 revision、文本哈希及源路径。sample_id 沿用 A/D 的申请 ID；B 的 `_t1` ID 在 profile JSON 的 prediction_sample_id 中。family_id 沿用历史 family_root，不表示家族覆盖已独立穷尽。
- `SOURCE_ROOTS.json`／`technical_source_manifest_portable.csv`：跨机器路径映射。使用按案给定的版本／文本哈希，不能从全局语料中补用后来版本。

## 方法与来源

模型固定为 BAAI/bge-m3，revision `{contract['revision']}`，1024 维，仅 CLS dense＋L2 归一化＋cosine。无 E5 query/passage 前缀、sparse、ColBERT 或 reranker。模型与 tokenizer 文件 SHA256、全部依赖、实际设备／精度及长文本规则保存在 embedding_contract.json。模型权重与完整向量缓存留在本机；此包提供缓存清单、校验和及完整实际编码技术文本。

查询使用目标 cutoff 输入清单里的日期合格 abstract／claims；没有日期版本证据的 title 明确缺失。历史技术文本不晚于对应 reply_date，并严格早于目标 cutoff。文件名／catalog／来源 manifest 核验一致。完整资格检查后，每申请固定最早合格 reply_date、episode_id；再按 cosine 排序并去重申请／家族。包含 allowance，不根据目标 O2、未来结局或测试效果选例。

预检发现并记录了 CLM 中的 SVG 元数据和少量混入的 examiner／art-unit／OA 论辩标记。前者以固定规则移除并保留原文／转换哈希；后者保守排除整个混杂字段，选择合格较早技术版本或记录缺失。未重建图形／化学式，也未修改冻结预测历史或 gold。source_flag_semantics.json 解释原文件标记与实际编码文本的区别。实际输入已完成已知身份／论辩／SVG 标记扫描；其他 OCR 与 claims 状态解析限制仍保留。

## 覆盖与新审核

原始检索 k 分布：{json.dumps(summary['raw_k_counts'],ensure_ascii=False)}。

交接实际 k 分布：{json.dumps(summary['effective_k_counts'],ensure_ascii=False)}。审核撤下 {summary['withheld_example_count']} 条弱相关例子，涉及 {summary['profiles_with_withheld_examples']} 份画像；只撤下原 top-3 的指定条目，不补例、不重排。`rank` 保留原 cosine 排序并完成家族去重后的 top-k 顺序，`rendered_rank` 表示在交接块中的显示顺序。统计卡与 raw／adjusted 数值、card_sha1 不变。full_ranking.csv 的 application_rank 是全部候选申请中的位置。

先完成固定三案预检，再审核原固定十案、全部三十版本；所有三百份均有日期、身份、家族、来源、摘要原文片段及哈希自动检查。**逐案语义技术复核仅覆盖原固定十案，不宣称三百份都已逐案相关性审核。审核人为 Codex 技术复核，不是 D/C 本人签字。** 原曾弱相关的案例没有被换掉，其原始排序、失败意见和撤下记录全部保留。

- `fixed_ten_final_review.csv`：候选／最终文件和正文哈希、保留及撤下案例、限定说明。
- `review/`：新预检与固定十案的原始 top-3 审阅材料；它展示撤下前的候选。
- `automatic_validation.json`／`automatic_profile_checks.csv`：对应最终交接文件；`raw_candidate_*` 仅对应撤下前候选。
- `ranking_top3_links_before_review.csv`／`review_withheld_examples.csv`：完整保留原排序与失败原因。

## 对照与展示

`old_vs_new_topk.csv` 保存旧 TF-IDF 与新原始 top-k 的 ID、episode 和相似度；`old_vs_new_effective_retrieval.csv` 另列最终实际提供的案例和 k。两种相似度来自不同表示／模型，不能直接比较其绝对数值大小。

`DISPLAY_EXAMPLES.md`／`actual_retrieval_input_output.json` 展示预先固定三案的实际技术输入、真实 dense 输出预览、top-3、分数、来源及保留状态。`MODEL_VISIBLE_PROFILE_EXAMPLE.txt` 是实际可发送的 profile_text；`prompts/` 保存共享模板和未改的预测系统提示，仅供展示。`code/` 保存实现、固定依赖、运行说明与测试。

## 结论边界与后续 B 工作

这是完整新检索／共享画像版本；不报告新预测分数或区间。新旧设置同时改变技术文本表示、编码器和相关性审核后的案例覆盖，不能把后续全部差异归因于编码器本身。

后续 B 预测仍使用 GPT-5-mini、Qwen3.6-27B 及原有各自推理设置、固定 GPT state、提示和评分规则；正式条件 no_profile／own／mismatched。共享 artunit 画像不等于启动 artunit 实验。旧无画像成功结果只有在完整请求／配置／输入一致时复用；旧 TF-IDF 画像预测仅作旧设置对照，不能替代新输入预测。

后续同样本比较保持原有效分母规则（Occ./Type 99、Grnd. 62）、restriction／112d／未知 ground 处理、family bootstrap 1000 次及 seed=20261010。D 的 top-3 平均是其轨迹任务的工作，不替代 B 三项基线。本包没有启动上述预测。

保留 A 家族范围、14353039 身份 fallback、有限且重叠的 artunit 池、assignment-only 归属、缺正文、近似 ground 标签及删失解释。日期合格的 claims 文书可能是提议修订，不等于已被 entered。Title 缺失表示本版未提取／验证该字段的日期版本，不断言原卷宗没有历史标题。

完整画像、实际技术文本、来源／审阅材料和缓存清单仅留在本地／团队包。未公开上传、未提交或推送；origin 仍指向 capstonetest，未来发布代码须显式核对 ProsecutionBench。

官方模型依据：[模型说明](https://huggingface.co/BAAI/bge-m3)，[固定 revision](https://huggingface.co/BAAI/bge-m3/commit/{contract['revision']})。
'''
(dest/'README.md').write_text(text)
print('Materials written to',dest)
