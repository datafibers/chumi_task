# Market Signal Intelligence Bot

一个用于演示“聊天数据流 → 市场信号抽取 → 聚合报表”的 Streamlit 应用。项目默认使用 OpenRouter 做结构化 LLM 抽取，也支持完全离线的 deterministic fake extractor。

## 1. 环境要求

- Python 3.9+
- OpenRouter API key（使用真实模型时需要）

安装依赖：

```bash
python -m pip install -r requirements.txt
```

## 2. 配置 OpenRouter

可以通过环境变量配置：

```bash
export OPENROUTER_API_KEY="your-api-key"
export OPENROUTER_MODEL="google/gemini-2.5-flash"
export OPENROUTER_FALLBACK_MODEL="google/gemini-2.5-pro"
```

也可以启动 Streamlit 后，在 `Control` 面板中填写 API key、primary model 和 fallback model。API key 只写入当前 Streamlit 进程的环境，不会写入源代码或数据库。

点击 `Save configuration` 后，UI 设置会自动保存到本机的 `.streamlit/user_settings.json`，下次启动会自动恢复。该文件已加入 `.gitignore`，不会提交到 Git；它包含本机明文 API key，请只在个人开发环境使用。

Control 面板预置了以下模型，也支持自定义 model slug：

- `google/gemini-3.8-flash`：最新 Flash，速度和复杂推理能力较强
- `google/gemini-3.1-pro-preview`：高质量 reasoning，成本更高
- `google/gemini-2.5-flash`：默认，速度快、成本较低
- `google/gemini-2.5-pro`：更强推理，适合作为 fallback
- `anthropic/claude-sonnet-4.5`：复杂语义抽取
- `openai/gpt-4.1-mini`：快速结构化抽取
- `openai/gpt-4.1`：更高质量

## 3. 启动 UI

```bash
streamlit run dashboard.py
```

打开终端显示的本地地址，通常是 `http://localhost:8501`。

应用有三个顶部页面（不使用侧边栏菜单）：

### Dashboard

显示 supply/demand、median price、P25/P75、resource trends、extracted signals、source message IDs、provenance、confidence、explanation 和 pipeline errors。Dashboard 会按刷新频率自动读取 JSONL stream 和 SQLite 状态。

### Settings

用于配置 OpenRouter API key、primary/fallback model、刷新频率、offline fake extractor，以及最低可接受 golden accuracy。选择 Offline demo mode 后，OpenRouter 的 key/model 配置会自动隐藏。

### Control

用于运行 golden regression tests 和 demo replay。如果最近一次 golden test 低于阈值，`Run demo` 会被禁用。

## 4. 在 Control 中切换真实/离线模式

推荐只用一个启动命令：

```bash
streamlit run dashboard.py
```

启动后进入 `Control` 面板，在同一个配置表单中选择：

- `Live OpenRouter mode` 开启：使用填写的 OpenRouter API key、primary model 和 fallback model
- `Live OpenRouter mode` 关闭：不需要 API key，不调用网络，使用 deterministic extractor

保存配置后，点击 `Run golden tests` 验证当前模式，再点击 `Run demo` 处理演示数据，最后返回 `Dashboard` 查看结果。这样不需要为了切换模式重新启动应用。

环境变量 `USE_FAKE_LLM` 仍然可以作为启动时的默认值，但不是必需的 UI 操作：

```bash
USE_FAKE_LLM=1 streamlit run dashboard.py
```

## 5. 模拟聊天数据流

在另一个终端运行：

```bash
python mock_producer.py --reset --interval 1
```

参数：`--reset` 清空并重建 stream；`--interval 1` 每条消息间隔 1 秒；`--interval 0` 快速回放全部 fixture。

推荐运行方式：

终端 1：`USE_FAKE_LLM=1 streamlit run dashboard.py`

终端 2：`python mock_producer.py --reset --interval 1`

## 6. Golden regression test

Golden cases 位于 `data/golden_cases.jsonl`，覆盖 correction、demand bound、GPU supply、historical chatter、bundled offer、commitment、availability 和 irrelevant message。

不启动 UI 也可以运行：

```bash
USE_FAKE_LLM=1 python -c "from src.pipeline.evaluation import run_golden_suite; print(run_golden_suite())"
```

结果包括 case 数量、实际测试的 input rows 数量、通过数量、field accuracy、每个 case 的字段检查和失败 case 的实际信号。

## 7. 配置变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `OPENROUTER_API_KEY` | none | OpenRouter credential |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | primary extraction model |
| `OPENROUTER_FALLBACK_MODEL` | `google/gemini-2.5-pro` | fallback model |
| `USE_FAKE_LLM` | `0` | 使用离线 extractor |
| `REPORT_REFRESH_SECONDS` | `5` | Dashboard 刷新间隔 |
| `GOLDEN_MIN_ACCURACY` | `0.75` | 允许运行 demo 的最低准确率 |
| `CHAT_SOURCE_FILE` | `data/chat_messages.jsonl` | 原始 fixture |
| `CHAT_STREAM_FILE` | `data/chat_stream.jsonl` | 模拟实时 stream |
| `MARKET_DB_FILE` | `data/market_signal.db` | SQLite 状态库 |
| `SNAPSHOT_FILE` | `data/snapshot.json` | snapshot 输出 |

## 8. Pipeline

```text
data/chat_messages.jsonl
  -> mock producer
  -> data/chat_stream.jsonl
  -> RawMessage validation
  -> reply/time-window context assembly
  -> OpenRouter structured extraction
  -> deterministic normalization and deduplication
  -> SQLite signal state
  -> aggregation
  -> Streamlit dashboard + data/snapshot.json
```

SQLite 保存 processed context keys、signal provenance 和 extraction failures。Correction 消息会根据 source message IDs 替换旧信号，避免旧价格继续出现在当前 snapshot 中。

## 9. 清理并重新运行

```bash
rm -f data/market_signal.db data/chat_stream.jsonl data/snapshot.json
python mock_producer.py --reset --interval 0
```

或者直接在 Control 面板点击 `Run demo`，它会自动重置 SQLite 状态并重新处理 fixture。

## 10. 设计文档

- [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md)
- [docs/USE_CASES.md](docs/USE_CASES.md)
- [docs/AI_Engineer_Take_Home_Market_Signal_Bot.pdf](docs/AI_Engineer_Take_Home_Market_Signal_Bot.pdf)
