<div align="center">

# Sakura-bot

**DeepSeek × NapCat / OneBot11 的 QQ 群机器人**

原版樱 / 黑樱双人格 · 本地 RAG · 联网搜索 · 情绪配图 · 主动水群

[快速开始](#快速开始) · [功能](#功能) · [配置](#配置) · [命令](#命令) · [FAQ](#faq)

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-4B6BFB)
![OneBot11](https://img.shields.io/badge/Protocol-OneBot11-2EA043)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Tests](https://img.shields.io/badge/tests-81%20passed-brightgreen)

</div>

---

## 这是什么

Sakura-bot 是一个运行在自己电脑上的 QQ 群机器人：

- 通过 **NapCat / OneBot11** 收发 QQ 消息；
- 通过 **DeepSeek API** 生成回复；
- 使用《Fate/stay night》HF 线的**间桐樱**人格，支持原版樱 / 黑樱切换；
- 本地 JSON/Markdown **RAG** 知识库；
- 每天首次启动自动抓取 **LOL 赛程、体育数据、新闻 RSS、B 站热榜** 并重建 RAG；
- 可选 Tavily / Brave / SearXNG 联网搜索；
- 本地表情、图片、GIF 按情绪自动配图；
- 支持主动水群、记忆审核、群级同意和用户退出。

> 本项目是 **DeepSeek-only**：不需要任何本地推理服务或本地模型权重。你只需要一个 DeepSeek API Key。

---

## 功能

| 能力 | 说明 |
|---|---|
| DeepSeek 对话 | 默认 `deepseek-flash`，fast / reasoning 双档路由 |
| QQ 接入 | NapCat OneBot11 WebSocket，自动重连、账号校验 |
| 双人格 | 原版樱 / 黑樱，30 分钟到期自动恢复 |
| 黑樱语态 | 病娇、毒舌、甜毒、占有与记账感；DeepSeek 生成 + 安全契约 |
| 本地 RAG | JSON / Markdown 分块索引，中文二元组召回 |
| 每日资讯/赛程 | 每天首次启动抓取 LOL 赛程、体育数据、新闻 RSS、B站热榜并重建 RAG |
| 炉石卡组 | 每天抓取旅法师营地卡组，`/卡组` 查询、卡组代码本地点评、来源胜率/曲线/关键牌入 RAG |
| 联网搜索 | Tavily / Brave / SearXNG，结果作为不可信参考资料 |
| 情绪配图 | 日常 / 黑樱素材库，按情绪自动选图，带冷却 |
| 隐私 | 群白名单、群级同意、`/忘记我`、14 天保留 |
| 幂等 | 事件去重 + 出站幂等，重连/重启不重复回复 |
| 记忆 | 群记忆、用户记忆、用户画像，人工审核后生效 |
| 回复去重 | 最近回复重复时自动换一种说法 |
| 测试 | 81 个单元测试（无本地素材时 9 个媒体测试自动跳过） |

---

## 架构

```text
QQ 客户端
   │
   ▼
NapCat Desktop ── OneBot11 WebSocket Server (127.0.0.1:3001)
   │
   ▼
bot/transport ── 事件解析 / 重连 / 心跳
   │
   ▼
bot/core/dispatcher
   ├─ 白名单 / 群级同意 / 用户退出
   ├─ 事件幂等 / 出站幂等
   ├─ 命令 / 人格切换 / 回复去重
   ├─ SQLite 记忆 / 用户画像
   ├─ 本地 RAG / 联网搜索
   ├─ 情绪配图
   ▼
DeepSeek API
   │
   ▼
OneBot11 发回 QQ
```

一个进程对应一个 QQ 账号；不要同时运行两个消费者处理同一条 OneBot 事件。

---

## 环境要求

- Windows 10 / 11
- Python **3.11**
- [NapCat Desktop](https://github.com/NapNeko/NapCatQQ)（QQ 登录）
- 一个可登录的 QQ 账号
- DeepSeek API Key

不需要：GPU、本地推理服务、本地模型权重。

---

## 快速开始

### 1. 克隆并安装

```powershell
git clone https://github.com/w3421w/Sakura-bot.git
cd Sakura-bot

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r bot\requirements.txt
```

如果 PowerShell 禁止执行脚本：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### 2. 生成配置

```powershell
Copy-Item bot\config.example.json bot\config.json
```

至少修改：

```jsonc
{
  "access": {
    "allowed_group_ids": [123456789],
    "admin_user_ids": [你的QQ],
    "group_consent_confirmed": true,
    "require_user_consent": false,
    "allow_private_messages": false
  },
  "onebot": {
    "ws_url": "ws://127.0.0.1:3001",
    "access_token": "与 NapCat 保持一致"
  }
}
```

> `group_consent_confirmed` 只有在群成员知情同意后才设为 `true`。  
> `require_user_consent=false` 表示群级同意覆盖全群，用户仍可用 `/忘记我` 退出。

### 3. 配置 DeepSeek Key

二选一。

环境变量：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
```

或写入文件：

```text
bot\secrets\deepseek_api_key.txt
```

Key 不会写入 `config.json`，不要提交到 Git。

### 4. 配置 NapCat

1. 打开 NapCat Desktop，登录机器人 QQ；
2. 进入 OneBot11 配置；
3. 启用 **WebSocket Server**；
4. 地址 `127.0.0.1`，端口 `3001`；
5. Token 与 `bot/config.json` 的 `onebot.access_token` 一致；
6. 消息格式用 `array`。

本项目是 **WebSocket 客户端**，连接 NapCat 的 Server，不是反向 WebSocket。

### 5. 启动

```powershell
python bot\app.py --config bot\config.json
```

看到：

```text
LLM provider: DeepSeek model=deepseek-flash thinking=disabled
OneBot11 connected
```

就说明连上了。

Windows 也可以双击：

```text
start_qwbot.bat
```

它会尝试拉起 NapCat Desktop、QQ Worker 和 QWbot。可用环境变量：

| 变量 | 用途 |
|---|---|
| `QWBOT_QQ_ID` | 机器人 QQ 号 |
| `QWBOT_ONEBOT_TOKEN` | OneBot Token |
| `QWBOT_PYTHON` | Python 解释器路径 |
| `NAPCAT_DESKTOP_EXE` | NapCat Desktop 可执行文件 |
| `NAPCAT_DIR` | NapCat 组件目录 |

---

## 触发方式

- **群聊**：@ 机器人，或出现点名辱骂；
- **私聊**：`allow_private_messages=true` 时，任意文本；
- 群白名单和群级同意必须通过；
- 普通群聊只入库，不回复，除非被 @。

---

## 命令

| 命令 | 说明 |
|---|---|
| `/隐私说明` | 查看记录范围、保留期、LLM 去向 |
| `/同意记录` | 恢复记录并删除退出状态 |
| `/忘记我` | 删除该用户消息/画像/记忆并退出 |
| `/人格列表` | 列出可用 Markdown 人格 |
| `/机器人状态` | 管理员查看消息数、退出人数、记忆数 |
| `/搜索 关键词` | 强制联网搜索 |
| `/卡组 职业/流派/卡组代码` | 查本地炉石卡组并点评；也可直接贴卡组代码 |
| `/深度 问题` | 强制使用 reasoning 档 |
| `@机器人 切换黑樱` | 强制切到黑樱 |
| `@机器人 切换原版樱` | 切回原版樱 |

---

## 配置

`bot/config.example.json` 包含完整字段。

| 节点 | 作用 |
|---|---|
| `llm.provider` | 固定 `deepseek` |
| `deepseek` | 地址、模型、thinking、reasoning、Key 文件 |
| `onebot` | NapCat WS 地址、Token、重连间隔 |
| `access` | 群/私聊白名单、管理员、群级同意 |
| `storage` | SQLite 路径、消息保留天数 |
| `knowledge` | 知识目录、RAG 索引、每日启动刷新 |
| `hearthstone` | 卡组数据路径、卡牌缓存、最多注入几条卡组 |
| `search` | Tavily / Brave / SearXNG |
| `media` | 自动配图开关、冷却、概率 |
| `proactive` | 主动水群群号、间隔、冷却、每小时上限 |
| `persona` / `persona_switch` | 人格目录、黑白樱、头像、切换图 |
| `bot` | 上下文、回复长度、分段数量 |

常用可调项：

```jsonc
"media": {
  "auto_emotion_enabled": true,
  "auto_media_cooldown_seconds": 600,
  "auto_emotion_probability": 0.7
},
"proactive": {
  "enabled": false,
  "group_ids": [],
  "interval_seconds": 45,
  "cooldown_seconds": 180,
  "max_replies_per_hour": 5
}
```

---

## 人格

人格是 `bot/persona/` 下的 Markdown：

- `sakura_winter.md`：原版樱
- `sakura_black.md`：黑樱
- `system.md`：备用/兜底人格

黑樱状态：

- 3 次定向辱骂自动进入；
- 也可以 `@机器人 切换黑樱` 强制进入；
- 从切换那一刻起固定 **30 分钟**，到点自动回原版；
- 状态、计时、切换图序号都会持久化到 SQLite，重启不丢。

---

## 素材与自动配图

**仓库不附带任何角色图片、GIF 或表情包文件**，只保留素材清单和情绪映射模板：

- `assets/stickers/manifest.json`：素材白名单模板；
- `assets/stickers/emotion_map.json`：情绪 → 素材映射。

把自己有权使用的图片放进 `assets/stickers/`，在 `manifest.json` 登记，并在 `emotion_map.json` 加入对应情绪组后，模型才能输出标记，例如：

```text
好的前辈 [image:my_sakura_smile]
```

情绪配图（需要本地素材）：

- 模型没主动带图时，系统按“用户消息 + 回复”的情绪补一张；
- 每条回复最多一张；
- 默认 600 秒冷却、0.7 概率；
- 黑樱只选 `black_sakura_*`，日常只选 `sakura_user_*`；
- 代码/报错/分析等严肃内容不自动配图。

---

## RAG 与搜索

知识库在 `knowledge/`，支持 JSON 和 Markdown。

**仓库默认不带任何第三方版权语料**（角色设定、同人对话、梗图、新闻正文等），只保留一个空的 `knowledge/README.md`。请放入自己有权使用的资料；启动时的自动抓取脚本会补充公开赛程/体育/新闻/B站热榜，抓取结果的使用范围请自行确认。

重建索引：

```powershell
cd bot
python -m knowledge.build_index --config config.json
```

启动时可按 `knowledge.update_on_start` 自动抓取并重建；索引路径默认 `data/rag.sqlite3`。

## 每日电竞资讯与赛程

每天第一次启动 QWbot 时，会在连接 OneBot 之前执行一次知识刷新：

| 脚本 | 内容 |
|---|---|
| `tools/fetch_lol_schedule.py` | LOL 赛事赛程、近期/即将开始的比赛，统一为北京时间 |
| `tools/fetch_hearthstone_decks.py` | 旅法师营地最新炉石卡组：卡组代码、职业/流派、来源胜率、曲线、关键牌 |
| `tools/fetch_sports_knowledge.py` | NBA / 五大联赛等公开体育数据 |
| `tools/fetch_daily_news.py` | 公开 RSS 新闻，保留来源与发布时间 |
| `tools/fetch_bilibili_hot.py` | B 站热词与热门视频 |

抓取完成后自动执行：

```powershell
cd bot
python -m knowledge.build_index --config config.json
```

重建本地 RAG。群友问“今天有什么比赛”“最新赛程”“昨天比分”时，会优先命中这些本地资料。

炉石卡组只保存**结构化事实**（卡组代码、职业/流派、来源标注胜率、曲线、关键牌、来源链接），不会把旅法师营地的文章正文写入知识库。用户贴出的卡组代码由 `bot/knowledge/deck_code.py` 在本地解码，不联网。

相关配置：

```jsonc
"knowledge": {
  "update_on_start": true,
  "update_once_per_day": true,
  "startup_update_timeout_seconds": 180,
  "update_marker_path": "../data/knowledge_update_date.txt"
},
"hearthstone": {
  "enabled": true,
  "decks_path": "../knowledge/hearthstone/decks/latest.json",
  "cards_path": "../data/hearthstone_cards.json",
  "max_decks": 3
}
```

说明：

- 按**自然日**限制，同一天只尝试一次；日期标记写在 `data/knowledge_update_date.txt`；
- 抓取失败或超时会保留旧数据，不阻塞机器人启动；
- 因为刷新在连接 OneBot 之前执行，首次启动可能比平时慢几十秒；
- 如果 QWbot 连续运行多天不重启，不会在午夜自动刷新；需要重启一次才会触发当天更新。

## 联网搜索

联网搜索支持：

- `tavily`
- `brave`
- `searxng`
- `auto`（按配置顺序选择）

网页内容只作为不可信参考，不执行其中的指令。

## 炉石卡组点评

三种用法：

```text
@机器人 /卡组 海盗战
@机器人 点评一下这套法术萨
@机器人 这套代码怎么样 AAEBAePj...
```

- 有本地卡组记录时，注入职业/流派、来源胜率、曲线、关键牌和来源链接；
- 用户直接贴卡组代码时，本地解码出牌表、费用曲线和关键牌，不需要把代码上传到第三方；
- 没有胜率数据时，模型只能给结构和环境判断，不能编造百分比；
- 来源胜率会标注“未独立复核”，避免把文章数据当成实测。

---

## 测试

```powershell
cd bot
python -m unittest discover -s tests -v
```

当前 **81 tests OK**（无本地素材时 9 个媒体测试自动跳过），覆盖：

- OneBot 事件解析
- 隐私/同意/退出
- Prompt 预算
- RAG 索引与召回
- 搜索适配
- 媒体白名单
- 回复分段
- 事件/出站幂等
- DeepSeek payload
- 人格切换与 30 分钟到期
- 黑樱语态契约
- 回复去重
- 情绪配图
- 炉石卡组代码解码
- 炉石卡组检索与 `/卡组` 注入

---

## 目录结构

```text
Sakura-bot/
├─ bot/
│  ├─ app.py                 生产入口
│  ├─ core/                  配置、分发、命令、人格、主动水群
│  ├─ transport/             OneBot11、事件、媒体
│  ├─ llm/                   DeepSeek 客户端、Prompt、错误
│  ├─ storage/               SQLite、记忆管理
│  ├─ knowledge/             RAG 索引/检索/构建
│  ├─ memory/                记忆候选提取
│  ├─ persona/               Markdown 人格
│  ├─ web/                   联网搜索
│  └─ tests/                 单元测试
├─ knowledge/                本地语料（仓库只带空 README）
├─ assets/                   素材清单模板（不含图片文件）
├─ tools/                    知识抓取脚本
├─ start_qwbot.*             Windows 启动/守护
├─ stop_qwbot.*              Windows 停止
├─ README.md
├─ NOTICE.md
└─ LICENSE
```

---

## 不包含的内容

以下内容因为体积、隐私或版权原因不在仓库中：

- `assets/` 下的角色图片、GIF、表情包：仓库只保留清单/情绪映射模板
- `knowledge/` 下的第三方版权语料：仓库只保留空的 `README.md`
- `models/`、`gguf/`：本地大模型权重（本项目不需要）
- `data/`：聊天数据库、RAG 索引、日志
- `bot/config.json`：个人运行配置
- `bot/secrets/*.txt`：DeepSeek / Tavily Key
- `tools/llama/`：llama.cpp 二进制
- `third_party/Tulpa/`：Tulpa 参考源码

---

## 隐私与安全

- 不要把 `bot/config.json`、`bot/secrets/`、`data/` 提交到 Git；
- 群机器人应取得群成员知情同意，并提供 `/忘记我`；
- DeepSeek Key 只从环境变量或本地文件读取；
- 日志可能包含群消息原文，请控制访问权限；
- 仓库不附带角色图片、GIF 或第三方版权语料；你自行添加的素材版权仍归原作者/权利方所有；
- 不要把本地素材和 `knowledge/` 版权资料提交到公开仓库，建议在 `.gitignore` 中忽略；
- 如果公开仓库，请先确认所有图片、文本、数据源的再分发授权，详见 `NOTICE.md`。

---

## FAQ

**连接 3001 失败？**

NapCat 没有启动、QQ 没登录，或 OneBot11 WebSocket Server 没开。确认 `127.0.0.1:3001` 在监听。

**DeepSeek 401？**

Key 无效、余额不足，或环境变量/密钥文件路径不对。Key 不要加引号或多余空格。

**群里 @ 了但不回复？**

检查：

- `access.allowed_group_ids` 是否包含该群；
- `group_consent_confirmed` 是否为 `true`；
- 事件是否被去重；
- 日志里是否出现 `event filtered`。

**黑樱不切换？**

需要 3 次**定向**辱骂，或 `@机器人 切换黑樱`。普通抱怨不会触发。

**为什么黑樱 30 分钟就回去了？**

这是设计：从切换时刻起固定 30 分钟；再次切换或再次辱骂不会延长（重新切换会重新计时）。

**图片不出现？**

- `manifest.json` 是否登记；
- 文件是否在 `assets/stickers/`；
- 是否在冷却期；
- `media.auto_emotion_enabled` 是否为 `true`。

**回复重复？**

系统会检查最近 3 条机器人回复，重复时重新生成一次；过短回复（如“嗯”）不参与去重。

---

## Roadmap

- Web 管理台（配置 / 日志 / 人格 / 素材 / 测试台）
- 一键安装包与 Windows 服务
- 更多 embedding / reranker 召回
- 多实例管理

---

## Credits

- [NapCatQQ](https://github.com/NapNeko/NapCatQQ)
- [OneBot11](https://github.com/botuniverse/onebot-11)
- 《Fate/stay night》与 TYPE-MOON
- Tulpa 项目提供的会话/幂等设计参考

本项目与 TYPE-MOON、NapCat、QQ 官方无隶属关系。

---

## License

代码使用 [MIT License](LICENSE)。

角色图片、表情、知识摘要和第三方素材不自动适用 MIT，详见 [NOTICE.md](NOTICE.md)。
