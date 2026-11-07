# GPT 队友：只需接收这一个私有包

分工：你只运行 GPT；B 负责固定输入、画像接入、旧 no_profile 核验、gold、统一评分和 GPT/Qwen 合并。无需重建检索、生成 state、拼画像或拿到评分标签。

## 准备一次

将 ZIP 解压到公开 Git 仓库以外的文件夹，在解压目录打开终端。需要 Python 3.11+。创建环境并安装：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows 可以将 `.venv/bin/python` 改为 `.venv\Scripts\python.exe`；下面隐藏输入示例适用于 macOS 的 zsh。包内运行配置不含密钥，保持原样；如果账户无法访问配置中的部署，请先联系 B，不自行换模型/部署并沿用旧基线。

## 只做四步

**1. 检查包和离线流程（不调用 API）：**

```sh
.venv/bin/python run_gpt.py check
```

看到 `checks_passed: true` 和 `api_calls: 0` 后继续。离线模拟包含预设的格式失败，用来检查失败记录及重试；它不会生成真实 dev 通过记录。

**2. 输入你自己的密钥，跑 3 件真实 dev：**

```zsh
read -s 'AZURE_OPENAI_API_KEY?Azure API key（隐藏输入）: '
export AZURE_OPENAI_API_KEY
printf '\n'
.venv/bin/python run_gpt.py dev
```

确认 `success_n: 3`、`failed_n: 0`。dev 不评分、不用来调提示。全部成功后自动生成与本包哈希绑定的通过记录；未通过不能跑正式批次。

**3. 正式预测并按需续跑：**

```sh
.venv/bin/python run_gpt.py core
```

依次运行 own 100 件、mismatched 100 件。每次未缓存 API 尝试默认间隔 65 秒；首次请求也等待，整批需数小时。停止后用同一命令续跑，成功结果保留，不改输入、不删缓存。不要同时启动两个进程。

完成时两组都应 `success_n: 100`、`failed_n: 0`。失败保留，不补默认预测。遇到模型版本、上下文或配置问题，把失败记录回传给 B；禁止静默截断、换提示或删样本。

**4. 打包回传：**

```sh
.venv/bin/python run_gpt.py export
```

把终端打印的 `*_RETURN_*.zip` 通过团队渠道回传给 B。它包含实际输入、请求与画像哈希对应、原始响应、全部用量/重试、缓存和结果，不含环境或 API key。未完成也可导出用于排查，会明确标记 incomplete，不冒充完成。

运行结束后：

```sh
unset AZURE_OPENAI_API_KEY
```

## 你不需要处理的内容

不跑 no_profile；B 已核验保留的旧基线。不要拿旧 TF-IDF 画像预测替代本包输入。你不需要 gold、评分脚本、完整历史原文、embedding 权重或缓存；也不需要另行下载 GitHub 代码覆盖这个已封存包。包内代码与公开交接版对应，输入/配置不可修改。

全部材料留在团队内部。包、原始输入和返回 ZIP 不提交到公开 GitHub。不要写入或发送 API key。

如果机器异常退出后提示 `.runner.lock`：先确认本包没有运行中的进程，再手动删除 `runs/gpt/.runner.lock` 后续跑；正常退出/Ctrl+C 会自动清理。
