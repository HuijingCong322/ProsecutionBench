# GPT 队友交接：只运行，不准备数据或评分

分工已经简化：**B 统一准备两模型输入、核验旧 no_profile、保管 gold 并完成评分；队友只跑 GPT 和回传结果。**

## 队友从这里开始

1. 向 B 接收一个私有包：`GPT_TEAMMATE_BGE_M3_v1_2026_11_06.zip`（约 7.9 MB）。
2. 在公开 Git 仓库之外解压。**包内已有最终输入、无密钥配置、冻结提示、代码与中文说明，无需再自行拼接或下载覆盖。**
3. 按 [四步运行说明](TEAM_README.md) 操作：检查 → 3 件真实 dev → own/mismatched 各 100 件 → 打包回传。
4. 返回生成的 `*_RETURN_*.zip` 给 B，不需要自己评分。

ZIP SHA256：`ef3b631f94a505deb1800b089cf5b3fdde65ca4720417c43931b8f37b02e817f`。包信息和输入哈希见 [PACKAGE_INFO.json](PACKAGE_INFO.json)。首次解压后运行 `run_gpt.py check` 会核验包内全部固定文件并做离线检查，不调用 API。

## 新入口的用途

[run_gpt.py](run_gpt.py) 是新版独立入口：

- 验证包、配置、输入和代码哈希，检查两条件基础消息/state 一致；
- dev 全部成功后生成与本包绑定的通过记录，未通过不能跑 core；
- 复用原 GPT runner 和限速代码，保留模型、提示、推理参数及重试规则；
- 每次请求保存 request_hash 与最终画像 provenance 的对应；
- 中断续跑保留成功结果；汇总部分写入或缓存丢失时仍可核验并恢复；
- export 收集原始响应、全部 attempt 用量、缓存及预测，明确标记完整/未完成；不包含 Python 环境或密钥。

入口默认读取脚本所在的**私有包**。公开 checkout 不含输入/配置，不能单独启动正式预测。

## 代码与验证

- `code/b_prediction.py`、`code/b_run_paced.py` 原样复用；[tests/test_run_gpt.py](tests/test_run_gpt.py) 检查新版入口的保护、追溯和续跑。
- `code/b_phase2_prediction.py`、`code/b_qwen.py` 保留为上一版参考；**不要运行旧第二阶段总入口**。
- `prompts/examiner_prediction.FROZEN.txt` 为未改的系统提示。
- `requirements.runtime.txt` 是私有包实际预测运行的固定依赖；`requirements.txt` 供公开代码与原测试使用。
- [SOURCE_MANIFEST_SHA256.json](SOURCE_MANIFEST_SHA256.json) 记录本目录公开文件校验和。

公开代码测试：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q -p no:cacheprovider tests
```

验证：38 项预测/新入口测试通过；原项目 121 通过、1 跳过。实际 200 条正式输入与 3 条 dev 完成离线核验，414 个共享 release 清单文件已校验。**新真实 GPT/Qwen API 调用为 0，真实 dev 尚未运行。**

## B 保管什么

B 保管 gold、taxonomy 例外、family 映射、旧 GPT/Qwen no_profile 成功结果、原始语料和审核包。无需让 GPT 队友分别接收或处理这些文件。B 的 Qwen 应使用私有包中相同的 own/mismatched 输入，核对 `PACKAGE_INFO.json` 的输入哈希；模型配置各自沿用原设置。

回收 GPT 结果后，B 统一核验所有请求/state/profile 哈希，并在同模型三条件共同成功样本上评分：Occ./Type 99、Grnd. 62（完整覆盖时）；保留 restriction、112d 和 unknown 处理；family bootstrap 1000 次，seed 20261010。报告 own−no_profile、mismatched−no_profile、own−mismatched。跨模型直接比较另核对共同样本。标签继续明确为自动草稿。

## 发布边界

这是公开的代码/说明目录。**私有 ZIP、基础输入、画像正文、gold、实际服务配置、API key、raw 输出和审阅材料不在 GitHub 上传。** 队友私有包不含 gold、旧无画像响应或完整审阅材料。本轮不生成预测效果结论。
