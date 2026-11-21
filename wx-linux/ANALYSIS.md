# 三个开源项目深度分析 & 落地路线图

> 生成时间：2026-11-14
> 针对项目：本机微信机器人（Linux 微信客户端 + LD_PRELOAD 页捕获 + OCR + LLM + 分析流水线）

## 三个项目各代表什么

| 项目 | 定位 | 对我们的价值 |
|---|---|---|
| Prometheus-first/helper | Windows 微信机器人框架（能力清单 + 工程结构） | **平台能力参考**：微信能做什么、版本怎么锁、配置怎么拆 |
| AstrBotDevs/AstrBot | 多平台 AI Agent 框架（架构教科书） | **消息处理架构**：stage 流水线、唤醒检测、记忆压缩、多人格 |
| SXP-Simon/astrbot_plugin_qq_group_daily_analysis | 群日常分析插件（功能最佳实践） | **分析/报告功能**：增量分析、任务状态机、消息清洗、统计画像 |

---

## 一、helper（能力 + 结构）

### 可借鉴的能力清单

| 能力 | 我方现状 | 借鉴 |
|---|---|---|
| 文本自动分段 | ✅ 已做多句连发 | — |
| 原生引用回复 | ❌ | 回复时引用对方，增强真人感 |
| 表情/语音/视频收发 | ❌ | 暂不急需 |
| 防撤回 | ❌ | 可做（拦截撤回事件） |
| 微信版本保护 | ❌ | **🔴 P0，最该抄** |
| 定时任务（cron） | 半（wxpipe 写死 5 分钟） | 做成 cron 配置 |
| 多账号管理 | ❌ | 暂不需要 |
| 插件系统 | ❌ | 配置拆解 + 插件化 |

### 工程结构（配置分离）

```
bot_config.json   后端、会话范围、插件开关
members_config.json  各群成员称呼与功能范围
llm_config.json   模型地址/密钥/模型名
tts_config.json   语音
```

> 我们目前一个 `wbot.json` 混着，应拆成 bot / llm / analysis 三份。

---

## 二、AstrBot（架构：stage 流水线）

核心 `pipeline/` 消息处理链路（顺序固定、可插拔）：

```
preprocess → rate_limit → content_safety → session_status
→ waking_check(唤醒/点名) → whitelist → process(调Agent)
→ respond → result_decorate
```

### 我们应重构成的 stage

```
① preprocess   ：归一化、剥离发送者前缀、去重
② rate_limit   ：冷却/频率（收敛现有的 cooldown）
③ content_safety：关键词黑名单（现无）
④ waking_check ：@我 / 叫名字 / 触发词（替代 mention_only 判断）
⑤ judge        ：主动参与判官（现散在循环）
⑥ agent        ：LLM 生成
⑦ respond      ：发送（send / send_image）
⑧ decorate     ：多句拆分、字数裁剪、去引号
```

### 其他可抄概念

- `waking_check` + `umo_auto_name`：**自动识别机器人昵称**，不硬编码 my_names
- `conversation_mgr`：**会话记忆 + 自动上下文压缩**（我们目前无上下文记忆）
- `persona_mgr`：**多人格切换**

---

## 三、daily_analysis（功能 + 工程质量）

DDD 分层：`domain`（实体/领域服务）/ `application`（用例）/ `infrastructure`（实现）。

### 可借鉴的关键服务

1. `task_state_machine` + `crash_recovery_service`：分析任务正式状态机 + 崩溃续跑
2. `message_cleaner_service`：专业消息清洗（系统消息/广告/去重/合并转发）
3. `statistics_service` + 用户画像：参与度、个性称号（"金句王""夜猫子"）
4. `incremental_merge_service`：多增量批次合并去重
5. `analysis_recovery_service`：分析结果快照复用（省 token）

---

## 落地路线图

| 优先级 | 任务 | 抄自 | 状态 |
|---|---|---|---|
| P0-1 | 微信版本锁定（防自动升级） | helper | ✅ |
| P0-2 | 消息处理重构为 stage 流水线 | AstrBot | ✅ |
| P1-1 | 自动识别机器人昵称 | AstrBot waking_check | ✅ |
| P1-2 | 群聊上下文记忆 + 自动压缩 | AstrBot conversation_mgr | ✅ |
| P1-3 | 分析任务状态机 + 崩溃续跑 | daily_analysis | ✅ |
| P2-1 | 消息清洗强化（根治串群） | daily_analysis cleaner | ✅ |
| P2-2 | 引用回复 | helper | ✅ |
| P2-3 | 报告加活跃度/用户画像/称号 | daily_analysis statistics | ✅ |
| P2-4 | 内容安全关键词 | AstrBot | ✅ |
| P2-5 | 多人格切换 | AstrBot persona | ✅ |
