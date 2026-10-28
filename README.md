# luo

文本优先的 AI 伙伴，v0.3。

## 快速开始

```bash
uv sync
cp .env.example .env          # Windows CMD: copy .env.example .env
# 在 .env 里填 DEEPSEEK_API_KEY
uv run luo
```

## 配置

`.env` 里可调：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | — | 必填 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 模型 ID |
| `HISTORY_LIMIT` | `20` | 启动时载入的消息条数 |
| `STARTUP_GREETING` | `true` | 有摘要/未完成的事时，启动先开口 |
| `STYLE_DEBUG` | `false` | 在终端标出命中的 AI 味说法 |

## 命令

| 命令 | 作用 |
| --- | --- |
| `/quit` `/exit` | 退出（退出时做一次记忆整理） |
| `/reset` | 清空本会话的事件、记忆和摘要 |
| `/memory` | 查看已抽取的记忆 |
| `/done <id>` | 把一条未完成的记忆标记为完成 |
| `/forget <id>` | 删除指定记忆 |
| `/remember <内容>` | 手动记一条事实 |
| `/promise <内容>` | 手动记一条没做完的事 |
| `/summary` | 查看最近的会话摘要 |
| `/help` | 显示帮助 |

## 典型用法

```text
uv run luo
/help
我叫小林，明天一起打末影龙吧
/quit

# 再启动一次
uv run luo
上次我们聊了什么？
/memory
/summary
```

退出时会抽取记忆和会话摘要，下次启动自动带上。

## 当前能力

- 终端对话，流式输出
- 人设内置反 AI 味约束；`STYLE_DEBUG=true` 可在终端看命中项
- 启动时如果有未完成的事或上次摘要，会先开口
- 原始消息持久化，启动时载入最近 20 条
- 每 6 轮或退出时抽取结构化记忆（kind / content / importance / status / source_event_ids）
- 承诺、约定以 `open` 保存，每轮优先注入；能从对话里识别完成，也可以 `/done <id>` 手动标记
- 每次退出生成 1-3 句会话摘要，下次启动时注入 system prompt
- 每轮按关键词 + 重要度 + 时间检索记忆，注入 system prompt
- 所有数据在本地 SQLite：`data/luo.db`

## 已知限制

- 只有终端通道，没有 QQ / 游戏接入
- 记忆检索是关键词 + 打分，不是向量检索
- 记忆抽取依赖模型输出 JSON；失败时会跳过这一轮
- 自动完成识别依赖模型判断，可能漏；`/done` 是兜底
- 反 AI 味目前是“人设约束 + 正则体检”，不是强制改写；模型仍可能偶尔说漏
- 单进程、单会话（`local`）

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。核心约束：**LLM 不在实时回路里**；反射 / 战术 / 社交三层各有延迟预算。接口骨架在 `src/luo/core/interfaces.py`。

## 下一步

- 聊天体验继续调：主动性、说话方式、回复节奏
- async 核心 + `ChatChannel`，然后接 QQ（OneBot，小号 + 白名单）
- Minecraft：Node 边车 + Mineflayer，Python 通过本地 WebSocket 调 `follow / goto / mine / place / craft / give` 等技能
- 记忆按 `user` 聚合，聊天、游戏、QQ 共享同一份记忆
- 检索升级：FTS5 / 向量，替换现在的关键词打分

## 测试

```bash
uv run pytest
```

## 目录

```
src/luo/
  config.py            # 配置（.env）
  llm.py               # DeepSeek / OpenAI 兼容客户端
  store.py             # SQLite：events + memories + sessions
  memory.py            # 抽取、打分、注入
  greeting.py          # 启动主动开口
  style.py             # AI 味体检
  channels/terminal.py # 终端 REPL
  core/interfaces.py   # 游戏无关接口（GameAdapter / Planner / ...）
  persona/system.md    # 人设
docs/ARCHITECTURE.md   # 三层循环与延迟预算
tests/
data/luo.db            # 运行时生成，已 gitignore
```
