# mute_user_plugin 群聊禁言插件

## 插件简介

`mute_user_plugin` 是一个用于 QQ 群聊的智能禁言插件，支持通过 LLM 智能判定和命令两种方式对成员进行禁言操作。插件支持灵活的权限管理、消息模板自定义、日志记录等功能，适用于需要自动化或半自动化群管理的场景。

## 功能特性

- **智能禁言 Action**：基于 LLM 判断聊天内容，自动决定是否需要禁言。
- **命令禁言 Command**：支持 `/mute 用户名 [时长(秒)] [理由]` 命令，管理员可手动禁言。
- **权限控制**：可配置允许使用禁言命令的用户和群组。
- **消息模板**：禁言成功或失败时可自定义提示消息。
- **日志记录**：支持详细的操作日志，便于追踪和审计。

## 配置说明

插件配置文件为 `config.toml`，支持以下主要配置项：

- `plugin.enabled`：是否启用插件
- `components.enable_smart_mute`：启用智能禁言 Action
- `components.enable_mute_command`：启用命令禁言 Command
- `permissions.allowed_users`：允许使用命令的用户列表
- `permissions.allowed_groups`：允许使用 Action 的群组列表
- `mute.templates`：禁言成功的消息模板
- `mute.error_messages`：错误消息模板

详细配置请参考插件目录下的 `config.toml` 文件。

## 使用方法

### 1. 智能禁言（Action）
- 插件会根据群聊内容自动判断是否需要禁言，无需手动触发。
- 需在配置中启用 `enable_smart_mute`，并设置好群组权限。

### 2. 命令禁言（Command）
- 管理员或有权限的用户可在群聊中输入：
  ```
  /mute 用户名 [时长(秒)] [理由]
  ```
  例如：`/mute 张三 3600 违规发言`
- 插件会自动查找用户并执行禁言操作，默认禁言时长为1小时（3600秒）。

## 技术细节

- 禁言操作通过调用 NapCatQQ 的 HTTP API 接口 `http://127.0.0.1:3000/set_group_ban` 实现。
- 请求体格式为：`{"group_id": "群号", "user_id": "用户QQ号", "duration": 禁言时长(秒)}`
- Action 和 Command 组件均支持详细的权限和参数校验。
- 插件基于麦麦插件系统开发，支持热插拔和灵活扩展。

## 适用场景

- 需要自动化管理 QQ 群聊成员发言的机器人项目
- 需要灵活权限和消息模板的群管理插件
- 需要结合 LLM 智能判定的群聊安全场景

## 目录结构

```
mute_user_plugin/
├── config.toml      # 插件配置文件
├── plugin.py        # 插件主程序
└── README.md        # 插件说明文档
```

## 联系与反馈

如有问题或建议，欢迎在项目仓库提交 issue 或联系开发者。
