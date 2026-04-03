# Mrpbot 

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制配置示例
cp config/bot.yaml.example config/bot.yaml

# 编辑配置
# 复制环境变量示例
cp .env.example .env

# 编辑 .env 填入 API Key
```

### 3. 启动

```bash
python main.py
```

---

## 📁 项目结构

```
Mrpbot2.0/
├── src/
│   ├── core/              # 核心层
│   │   ├── __init__.py
│   │   ├── bot.py         # 机器人主类
│   │   ├── engine.py      # 消息引擎
│   │   └── lifecycle.py   # 生命周期管理
│   │
│   ├── channels/          # 通信渠道
│   │   ├── __init__.py
│   │   └── onebot.py      # OneBot 协议
│   │
│   ├── features/          # 功能模块
│   │   ├── __init__.py
│   │   ├── chat/          # 聊天
│   │   ├── games/         # 游戏
│   │   ├── group/         # 群聊
│   │   ├── memory/        # 记忆
│   │   └── proactive/     # 主动消息
│   │
│   ├── llm/               # AI 服务
│   │   ├── __init__.py
│   │   └── client.py      # LLM 客户端
│   │
│   ├── tools/             # 工具系统
│   │   ├── __init__.py
│   │   ├── base.py        # 工具基类
│   │   └── registry.py    # 工具注册表
│   │
│   └── utils/             # 工具函数
│       ├── __init__.py
│       ├── logger.py      # 日志
│       └── config.py      # 配置
│
├── config/                # 配置文件
├── memory/                # 记忆存储
├── logs/                  # 日志
├── main.py                # 主入口
├── requirements.txt       # 依赖
└── README.md              # 文档
```

---

## 🎯 核心功能

### 1. 智能聊天
- 基于 LLM 的自然对话
- 上下文记忆
- 流式回复

### 2. 记忆系统
- 短期记忆（最近 100 条）
- 长期记忆（curated）
- 自动保存
- 快速检索

### 3. 群聊策略
- 回复欲望系统
- 智能冷却
- @必回机制
- 避免刷屏

### 4. 主动消息
- 定时问候
- 智能提醒
- 心跳检测

---

## 📖 详细文档

- [架构文档](ARCHITECTURE.md)
- [配置指南](config/README.md)
- [开发文档](docs/DEV.md)

---

