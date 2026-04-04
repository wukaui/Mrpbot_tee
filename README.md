# Mrpbot

Mrpbot 是一个基于 OneBot 的异步 QQ 机器人项目，当前实现围绕“消息接入 -> 回复判定 -> LLM 生成 -> 记忆持久化”这条主链路展开。它支持群聊、私聊、记忆、主动任务，以及基于人设的回复风格控制。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制配置示例
copy config\bot.yaml.example config\bot.yaml

# 编辑 config\bot.yaml 和 .env，填入 OneBot / LLM 所需参数
```

### 3. 启动

```bash
python main.py
```

## 项目结构

```text
Mprbot_tee/
├── main.py                # 程序入口
├── config/
│   ├── bot.yaml.example   # 配置示例
│   ├── bot.yaml           # 实际配置
│   └── characters/        # 人设文件
├── src/
│   ├── core/              # 启动、消息引擎、生命周期、元裁决
│   ├── channels/          # OneBot 通信层
│   ├── features/          # chat / group / memory / proactive
│   ├── llm/               # LLM 客户端
│   ├── persona/           # 人设管理
│   └── utils/             # 配置与日志
├── memory/                # 长期记忆
├── memory_auto/           # 自动记忆落盘
├── logs/                  # 日志输出
└── docs/                  # 补充文档
```

## 当前功能

### 聊天与回复

- 基于 LLM 的自然回复
- 支持私聊和群聊
- 群聊里包含回复欲望、冷却、静默窗口和元 AI 裁决
- 仅在实际发送成功后更新冷却

### 记忆系统

- 短期记忆按用户 / 群时间线保存
- 长期记忆保存到 `memory/long_term.md`
- 自动记忆保存到 `memory_auto/*.json`
- 关闭时和生命周期任务都会触发保存

### 人设系统

- 支持 `persona.system_prompt`
- 支持 `persona.file`
- 支持 `persona.name -> config/characters/<name>.md`
- 兼容旧字段 `bot.character` / `bot.identity_file`

### 群聊策略

- @ 或叫名字可触发必回
- 回复欲望采用信号叠加 + 时间衰减
- 元 AI 会按更接近人的方式判断 reply / wait / skip
- 支持停口令与分段输入合并

## 配置入口

- 主配置：[`config/bot.yaml.example`](config/bot.yaml.example)
- 人设说明：[`docs/CHARACTERS.md`](docs/CHARACTERS.md)
- 架构说明：[`ARCHITECTURE.md`](ARCHITECTURE.md)

## 说明

- 当前代码入口是 `main.py`
- OneBot 通道与 LLM 客户端都通过 `src/core/bot.py` 和 `src/core/engine.py` 串起来
- README 里的旧目录说明已过时，以当前仓库结构和代码实现为准

