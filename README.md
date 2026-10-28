# luo

文本优先的 AI 伙伴，v0.6。

## 快速开始

```bash
uv sync
cp .env.example .env          # Windows CMD: copy .env.example .env
# 在 .env 里填 DEEPSEEK_API_KEY
uv run luo
```

## 一键启动（QQ）

双击 `start-qq.bat`：它会先启动 NapCat，再启动 `luo-qq`。

- 脚本顶部的 `NAPCAT_DIR` / `PROJECT_DIR` 是写死的，换路径改那两行
- NapCat 已在运行（3001 端口监听）时，脚本会跳过启动；第一次扫码后保持 NapCat 窗口开着，之后不会再弹二维码
- `napcat.quick.bat` 里已经填好小号 QQ，但 quick 登录不一定每次都生效；不行就用 `napcat.bat` 手动扫码
- 停止：在 `luo-qq` 窗口 `Ctrl+C`，再关 NapCat 窗口
- 不要同时开 `uv run luo` 和 `uv run luo-qq`（共用 `local` session）

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
| `QQ_WS_URL` | `ws://127.0.0.1:3001` | NapCat OneBot 11 WebSocket 地址 |
| `QQ_ACCESS_TOKEN` | — | NapCat 的 access token |
| `QQ_ALLOWED_USERS` | — | 允许私聊的 QQ 号，逗号分隔；留空拒绝启动 |
| `QQ_SELF_ID` | — | 小号自己的 QQ 号，可选 |
| `SESSION_ALIASES` | — | 跨通道身份映射，例 `qq:123456=local` |
| `PROACTIVE_ENABLED` | `true` | QQ 空闲且有待办时，是否主动发一句 |
| `PROACTIVE_IDLE_MINUTES` | `120` | 空闲多久后考虑主动消息 |
| `PROACTIVE_COOLDOWN_MINUTES` | `720` | 两次主动消息的最小间隔 |
| `PROACTIVE_CHECK_SECONDS` | `60` | 检查间隔 |

## QQ（NapCat，私聊）

先安装 NapCat，用**小号**登录，在 WebUI 开启 WebSocket Server（`127.0.0.1:3001`，消息格式选 `array`，设置 token）。

`.env`：

```text
QQ_WS_URL=ws://127.0.0.1:3001
QQ_ACCESS_TOKEN=你的token
QQ_ALLOWED_USERS=你的主号QQ
QQ_SELF_ID=小号QQ
```

运行：

```bash
uv run luo-qq
```

只处理私聊；只回复白名单；群消息忽略。第三方协议违反 QQ 用户协议，有封号风险，**只用小号**。

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
- async 运行时 + `ChatChannel`；终端和 QQ 私聊都是通道
- QQ 私聊（OneBot 11 / NapCat），按 QQ 号拆 session
- 跨通道身份映射：`SESSION_ALIASES` 可让 QQ 主号和终端共用同一份 history / 记忆 / open loop
- 主动跟进：QQ 会话空闲且还有未完成的事时，会主动发一句（可关）
- 人设内置反 AI 味约束；`STYLE_DEBUG=true` 可在终端看命中项
- 启动时如果有未完成的事或上次摘要，会先开口
- 原始消息持久化，启动时载入最近 20 条
- 每 6 轮或退出时抽取结构化记忆（kind / content / importance / status / source_event_ids）
- 承诺、约定以 `open` 保存，每轮优先注入；能从对话里识别完成，也可以 `/done <id>` 手动标记
- 每次退出生成 1-3 句会话摘要，下次启动时注入 system prompt
- 每轮按关键词 + 重要度 + 时间检索记忆，注入 system prompt
- 所有数据在本地 SQLite：`data/luo.db`

## 已知限制

- QQ 只支持私聊文本；图片/语音只以占位符进入上下文，群聊未实现
- QQ 依赖 NapCat；第三方协议有封号风险，只用小号、白名单、低频
- 记忆检索是关键词 + 打分，不是向量检索
- 记忆抽取依赖模型输出 JSON；失败时会跳过这一轮
- 自动完成识别依赖模型判断，可能漏；`/done` 是兜底
- 反 AI 味目前是“人设约束 + 正则体检”，不是强制改写；模型仍可能偶尔说漏
- 单进程；同一用户的消息串行处理，还没有多会话并发调度
- 主动消息只在 QQ；冷却计时是进程内的，重启会重置

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。核心约束：**LLM 不在实时回路里**；反射 / 战术 / 社交三层各有延迟预算。接口骨架在 `src/luo/core/interfaces.py`。

## 下一步

- 事件总线 / 多用户并发（主动性调度已做）
- QQ 稳定性：NapCat 掉线重连、限流、消息分条
- Minecraft：Node 边车 + Mineflayer，Python 通过本地 WebSocket 调 `follow / goto / mine / place / craft / give` 等技能
- 游戏事件复用 QQ 的按用户 session，聊天和游戏共享同一份记忆
- 检索升级：FTS5 / 向量，替换现在的关键词打分

## 测试

```bash
uv run pytest
```

## 目录

```
src/luo/
  config.py            # 配置（.env）
  llm.py               # DeepSeek 同步 / 异步客户端
  store.py             # SQLite：events + memories + sessions
  memory.py            # 抽取、打分、注入
  chat.py              # 消息组装与同步回合
  runtime.py           # async 运行时、命令、关闭流程
  greeting.py          # 启动主动开口
  style.py             # AI 味体检
  channels/base.py     # ChatChannel 基类
  channels/terminal.py # 终端通道
  channels/qq.py       # OneBot 11 私聊通道（NapCat）
  core/interfaces.py   # 游戏无关接口（GameAdapter / Planner / ...）
  persona/system.md    # 人设
docs/ARCHITECTURE.md   # 三层循环与延迟预算
start-qq.bat           # Windows 一键启动 QQ 模式
tests/
data/luo.db            # 运行时生成，已 gitignore
```
