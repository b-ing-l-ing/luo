# luo

文本优先的 AI 伙伴，v0.8。

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
| `HISTORY_CHAR_LIMIT` | `4000` | 历史再按字符数裁一次 |
| `MEMORY_BLOCK_CHARS` | `1200` | 注入的记忆块总字数上限 |
| `MEMORY_LINE_CHARS` | `120` | 单条记忆注入时的字数上限 |
| `TOOL_RESULT_CHARS` | `1500` | 工具结果回灌给模型前的截断长度 |
| `CONTEXT_DEBUG` | `false` | 在日志里打印每轮上下文大小 |
| `STARTUP_GREETING` | `true` | 有摘要/未完成的事时，启动先开口 |
| `STYLE_DEBUG` | `false` | 在终端标出命中的 AI 味说法 |
| `QQ_WS_URL` | `ws://127.0.0.1:3001` | NapCat OneBot 11 WebSocket 地址 |
| `QQ_ACCESS_TOKEN` | — | NapCat 的 access token |
| `QQ_ALLOWED_USERS` | — | 允许私聊的 QQ 号，逗号分隔；留空拒绝启动 |
| `QQ_SELF_ID` | — | 小号自己的 QQ 号，可选 |
| `QQ_BURST_MAX` | `3` | 分条回复最多几条 |
| `QQ_BURST_DELAY` | `0.8` | 分条间隔秒数 |
| `WEB_SEARCH_ENABLED` | `true` | 是否给模型联网搜索工具 |
| `WEB_SEARCH_PROVIDER` | `auto` | `auto` / `deepseek` / `bing` |
| `WEB_SEARCH_MODEL` | `deepseek-v4-flash` | 搜索用的模型 |
| `WEB_SEARCH_MAX_RESULTS` | `5` | 每次搜索返回条数 |
| `AUTO_SAVE_WEB_MEMES` | `true` | 联网搜到的梗图发送后自动存库 |
| `WEB_MEME_MAX_PER_HOUR` | `3` | 每小时最多搜几张网图 |
| `MC_WS_URL` | `ws://127.0.0.1:3002` | Mineflayer 边车的 WebSocket 地址 |
| `MC_BOT_NAME` | `LuoBot` | 游戏里洛的 ID |
| `MC_ALLOWED_PLAYERS` | — | 允许对话的玩家名，逗号分隔；留空允许所有 |
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

## Minecraft（本地离线服）

- `mc-server/`：Paper 1.21.8，`online-mode=false`，只监听 `127.0.0.1:25565`，难度先设为 `peaceful`（方便测身体）；服务端用 PCL 自带的 Java 21
- `bot/`：Mineflayer 边车，在 `127.0.0.1:3002` 开 WebSocket 给 Python 调
- 一键启动：双击 `start-mc.bat`（起服务端 → 等 25565 → 起 Mineflayer 边车 → 起 `luo-mc`）
- 客户端：Minecraft **1.21.8**（你 PCL 里已有原版），服务器地址 `127.0.0.1:25565`
- 游戏内直接和洛说话：简单指令在本地秒回，不走大模型
  - `洛，跟着我` / `跟我来` / `过来` → 跟着说话的人
  - `洛，停下` / `别动` / `别挖了` → 停止移动，并打断正在进行的采集/送东西
  - `洛，你在哪` / `什么状态` → 报坐标、血量、饥饿、背包、附近玩家
  - `洛，背包里有什么` → 报背包
  - `洛，挖点木头` / `挖八块石头` → 采集附近方块（后台执行，做完会播报）
  - `洛，给我点木头` → 走过去把东西丢给说话的人（后台执行）
- 采集/送东西是后台动作：指令立即回、动作不阻塞聊天；做完通过 `action_done` 事件播报，失败会说“没干成”。
- 其他聊天走正常对话模型，模型可用 `mc_follow` / `mc_stop` / `mc_goto` / `mc_state` / `mc_inventory` / `mc_collect` / `mc_give` 操作游戏。
- 死亡、玩家进出服、洛自己的动作结果会作为“系统事件”写进上下文；记忆整理时可以把它们记成共同经历。
- 旧的 `!follow` / `!stop` / `!state` / `!goto x y z` / `!say 内容` 仍然可用，方便直接测身体。
- 游戏会话和终端 / QQ 主号共用 `local`（见 `SESSION_ALIASES`），记忆是通的。
- 采集范围 48 格，找最近的几块；石头/矿石需要镐子，木头可以直接用手砍。世界目前是 `peaceful`，不用担心怪。

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
| `/meme <标签>` | 发一张本地 `memes/` 梗图 |
| `/stickers [关键词]` | 同步/查看 QQ 收藏表情 |
| `/annotate [数量]` | 看图给收藏表情补描述/标签 |
| `/sticker <id/描述>` | 发一张 QQ 收藏表情 |
| `/webmeme <搜索词>` | 联网搜一张梗图并自动存库 |
| `/save [标签]` | 把最近收到的图存进 `memes/` |
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
- QQ 图片理解：发给它的图片会以多模态方式进入当前回合（`deepseek-flash`）
- QQ 分条回复：模型用空行分条，最多 3 条，条间隔 0.8s
- 本地梗图库：把图片放进 `memes/`，文件名就是标签；模型可调用 `send_meme`，也可 `/meme 无语` 手动发
- 存图：发图后说“存这张图”或 `/save 无语`，会把最近一张图存进 `memes/`
- QQ 收藏表情：同步小号的收藏，模型可调用 `list_stickers` / `send_sticker`；也可 `/stickers` / `/sticker <id/描述>`
- 收藏表情没有备注时，`annotate_stickers` 会看图自动补描述和标签（`/annotate`）
- 联网搜梗图：本地没有合适的时，模型可调用 `send_web_meme`；发送后自动存库，每小时最多 3 张
- 同类梗图有多张时随机发，但偏向较新的图（文件名可用编号，如 `无语_2.png`）
- 按需联网搜索：模型自己决定是否调用 `web_search`；DeepSeek 原生搜索，Bing RSS 兜底
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

- QQ 只支持私聊；图片能看，语音/视频还不支持，群聊未实现
- 图片只用于当前回合，不写入长期记忆；历史里只留 `[图片]` 占位
- 联网搜梗图走百度/Bing 图片；可能搜到不合适或版权图，自动存库可用 `AUTO_SAVE_WEB_MEMES=false` 关闭
- QQ 收藏表情需要先在小号里收藏；同步依赖 NapCat 的 `fetch_custom_face_detail`；空收藏会提示你
- 自动补备注依赖多模态模型，一次整理少量即可，别一次性刷很多
- 梗图库单张建议 <2MB；最近图片只缓存 3 张且在进程内，重启后“存这张图”需要先重新发图
- QQ 依赖 NapCat；第三方协议有封号风险，只用小号、白名单、低频
- 联网搜索在主源不可用时会回退 Bing；当前网络下 Bing 不稳定
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
  search.py            # 联网搜索（DeepSeek 原生 + Bing RSS 兜底）
  images.py            # 图片 data URL 解析与保存
  memes.py             # 本地梗图库与 send_meme 工具
  stickers.py          # QQ 收藏表情同步与发送
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
start-mc.bat           # Windows 一键启动 MC 服 + Mineflayer bot
bot/                   # Mineflayer 边车（当前用 ! 命令控制）
mc-server/             # Paper 服务端（jar/world/cache 已 gitignore）
memes/                 # 本地梗图库（图片已 gitignore，保留 README）
state/stickers.json    # QQ 收藏表情库，运行时生成，已 gitignore
tests/
data/luo.db            # 运行时生成，已 gitignore
```
