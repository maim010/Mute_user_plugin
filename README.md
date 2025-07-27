# send_group_notice_plugin 群聊发布公告插件

## 插件简介

`send_group_notice_plugin` 是一个用于 QQ 群聊的智能发布公告插件，支持通过 LLM 智能判定和命令两种方式发布群组公告。插件支持灵活的权限管理、消息模板自定义、日志记录等功能，适用于需要自动化或半自动化群管理的场景。

## 功能特性

- **智能发布公告 Action**：基于 LLM 判断聊天内容，自动决定是否需要发布公告。
- **命令发布公告 Command**：支持 `/send_notice 公告内容 [--image=图片链接] [理由]` 命令，管理员可手动发布公告。
- **权限控制**：可配置允许使用发布公告命令的用户和群组。
- **消息模板**：发布公告成功或失败时可自定义提示消息。
- **日志记录**：支持详细的操作日志，便于追踪和审计。

## 配置说明

插件配置文件为 `config.toml`，支持以下主要配置项：

- `plugin.enabled`：是否启用插件
- `components.enable_smart_notice`：启用智能发布公告 Action
- `components.enable_notice_command`：启用命令发布公告 Command
- `permissions.allowed_users`：允许使用命令的用户列表
- `permissions.allowed_groups`：允许使用 Action 的群组列表
- `notice.templates`：发布公告成功的消息模板
- `notice.error_messages`：错误消息模板

详细配置请参考插件目录下的 `config.toml` 文件。

## 使用方法

### 1. 智能发布公告（Action）
- 插件会根据群聊内容自动判断是否需要发布公告，无需手动触发。
- 需在配置中启用 `enable_smart_notice`，并设置好群组权限。

### 2. 命令发布公告（Command）
- 管理员或有权限的用户可在群聊中输入：
  ```
  /send_notice 公告内容 [--image=图片链接] [理由]
  ```
  例如：
  - `/send_notice 重要通知：明天服务器维护`
  - `/send_notice 活动安排 --image=https://example.com/image.jpg 活动宣传`
- 插件会自动执行发布公告操作。

## 技术细节

- 发布公告操作通过调用 NapCatQQ 的 HTTP API 接口 `http://127.0.0.1:3000/_send_group_notice` 实现。
- 请求体格式为：`{"group_id": "群号", "content": "公告内容", "image": "图片链接"}`
- Action 和 Command 组件均支持详细的权限和参数校验。
- 插件基于麦麦插件系统开发，支持热插拔和灵活扩展。

## 适用场景

- 需要自动化发布 QQ 群公告的机器人项目
- 需要灵活权限和消息模板的群管理插件
- 需要结合 LLM 智能判定的群聊管理场景

## 目录结构

```
send_group_notice_plugin/
├── config.toml      # 插件配置文件
├── plugin.py        # 插件主程序
└── README.md        # 插件说明文档
```

## 联系与反馈

如有问题或建议，欢迎在项目仓库提交 issue 或联系开发者。
