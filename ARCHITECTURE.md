# Mrpbot  架构文档

## 架构概览

```text
main.py
  -> src/core/bot.py (Mrpbot)
      -> src/channels/onebot.py (消息接入/发送)
      -> src/core/engine.py (消息处理主流程)
        -> src/llm/client.py (LLM 调用)
           -> src/persona/manager.py (人设加载与回退)
          -> src/features/memory/__init__.py (记忆系统)
      -> src/core/lifecycle.py (心跳/自动保存/状态检查)
```

系统职责分层：

- 入口层：启动、信号处理、退出码管理
- 核心层：组件初始化顺序、消息决策、生命周期任务
- 渠道层：OneBot WebSocket 收发与重连
- 服务层：LLM 客户端、记忆持久化
- 功能层：chat/group/memory/proactive 模块化封装

## 目录结构（当前实现）

```text
Mprbot_tee/
├── main.py
├── config/
│   ├── bot.yaml
│   ├── bot.yaml.example
│   └── characters/
├── src/
│   ├── core/
│   │   ├── bot.py
│   │   ├── engine.py
│   │   └── lifecycle.py
│   ├── channels/
│   │   └── onebot.py
│   ├── features/
│   │   ├── chat/
│   │   ├── group/
│   │   ├── memory/
│   │   └── proactive/
│   ├── llm/
│   │   └── client.py
│   ├── persona/
│   │   ├── __init__.py
│   │   └── manager.py
│   └── utils/
│       ├── config.py
│       └── logger.py
├── memory/
├── memory_auto/
├── logs/
└── docs/
```

## 启动与生命周期

1. `main.py` 加载 `.env` 与 `config/bot.yaml`
2. `Mrpbot.start()` 按顺序初始化：
   - 渠道（OneBot）
   - 消息引擎（LLM + PersonaManager + MemorySystem）
   - 功能模块（chat/group/memory/proactive）
   - 生命周期管理器（后台任务）
3. 生命周期后台任务：
   - 心跳日志（每 60s）
   - 自动保存记忆（每 300s）
   - 状态检查（每 600s）

## 消息处理主流程

位于 `MessageEngine.process_message()`：

1. 校验消息字段（`user_id`、`message`）
2. 统一将 OneBot 消息段转换为纯文本
3. 写入短期记忆
4. 更新回复欲望值
5. 判断是否应答（规则 + LLM 评分 + 冷却）
6. 生成回复并通过 OneBot 发送
7. 仅在成功发送后更新冷却截止时间

## 回复欲望逻辑（当前实现）

### 欲望值更新

以会话维度维护 `reply_desire`：

- 群聊键：`group_<group_id>`
- 私聊键：`user_<user_id>`

每条消息的增益：

- 被 @ 或叫机器人名字：`+20`
- 有趣关键词（如 `哈哈/233`）：`+10`
- 提问语气（如 `? / 吗 / 怎么`）：`+15`

然后执行：

$$desire = \min(100, desire + gain) - decay\_rate$$

默认 `decay_rate = 0.1`（可配）。

### 是否回复

群聊判定顺序：

1. `@机器人` 且 `reply_when_mentioned=true`：必回
2. 叫机器人名字：必回
3. 若在冷却期：不回
4. 否则请求 LLM 评分 `score`（0-100），与欲望阈值联合判定：
   - `score >= 80`：回复
   - `score >= 60 and desire >= threshold`：回复
   - `score >= 40 and desire >= threshold + 10`：回复
   - 否则不回

私聊当前策略：必回。

### 冷却机制

- 冷却时长来自 `features.group.cooldown`
- 仅在“实际发送成功”后写入冷却时间
- 冷却检查在群聊非必回路径生效

## 记忆系统

`MemorySystem` 提供：

- 短期记忆：按用户/群用户维度维护消息列表，默认最多 `100` 条
- 长期记忆：`memory/long_term.md`
- 自动记忆文件：`memory_auto/*.json`
- 生命周期任务与引擎关闭时都会触发保存

