"""
发群公告插件

提供智能发群公告功能的群聊管理插件。

功能特性：
- 智能LLM判定：根据聊天内容智能判断是否需要发布公告
- 模板化消息：支持自定义发布公告提示消息
- 参数验证：完整的输入参数验证和错误处理
- 配置文件支持：所有设置可通过配置文件调整
- 权限管理：支持用户权限和群组权限控制

包含组件：
- 智能发布公告Action - 基于LLM判断是否需要发布公告（支持群组权限控制）
- 发布公告命令Command - 手动执行发布公告操作（支持用户权限控制）
"""

from typing import List, Tuple, Type, Optional
import random

from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.base_plugin import register_plugin
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo, ActionActivationType, ChatMode
from src.plugin_system.base.config_types import ConfigField
from src.common.logger import get_logger
from src.plugin_system.apis import generator_api

logger = get_logger("send_group_notice_plugin")

# ===== Action组件 =====

class SendGroupNoticeAction(BaseAction):
    """智能发布公告Action - 基于LLM智能判断是否需要发布公告"""

    focus_activation_type = ActionActivationType.LLM_JUDGE
    normal_activation_type = ActionActivationType.KEYWORD
    mode_enable = ChatMode.ALL
    parallel_action = True

    action_name = "send_group_notice"
    action_description = "智能发布公告系统，基于LLM判断是否需要发布公告"

    activation_keywords = ["发公告", "发布公告", "群公告", "公告", "send notice", "group notice"]
    keyword_case_sensitive = False

    llm_judge_prompt = """
你是有温度的赛博群友，而非机械执行程序。发布公告决策需综合聊天语境和群组需求判断是否需要使用发布公告动作

发布公告动作的严格条件：

使用发布公告的情况：
1. 群主或管理员明确要求发布公告
2. 重要通知需要告知所有群成员
3. 活动安排需要提前通知
4. 规则变更需要公示
5. 紧急事项需要立即通知

绝对不要使用的情况：
1. 没有明确授权的情况下擅自发布公告
2. 内容不重要或不相关的公告
3. 发布过于频繁影响群成员体验
4. 包含敏感或违规内容的公告
"""

    action_parameters = {
        "content": "公告内容，必填，请确保内容准确、简洁且符合群组主题",
        "image": "公告图片链接，可选，可以为空",
        "reason": "发布公告理由，可选",
    }

    action_require = [
        "当群主或管理员明确要求发布公告时使用",
        "当有重要通知需要告知所有群成员时使用",
        "当活动安排需要提前通知时使用",
    ]

    associated_types = ["text", "command"]

    def _check_group_permission(self) -> Tuple[bool, Optional[str]]:
        if not self.is_group:
            return False, "发布公告动作只能在群聊中使用"
        allowed_groups = self.get_config("permissions.allowed_groups", [])
        if not allowed_groups:
            logger.info(f"{self.log_prefix} 群组权限未配置，允许所有群使用发布公告动作")
            return True, None
        current_group_key = f"{self.platform}:{self.group_id}"
        for allowed_group in allowed_groups:
            if allowed_group == current_group_key:
                logger.info(f"{self.log_prefix} 群组 {current_group_key} 有发布公告动作权限")
                return True, None
        logger.warning(f"{self.log_prefix} 群组 {current_group_key} 没有发布公告动作权限")
        return False, "当前群组没有使用发布公告动作的权限"

    async def execute(self) -> Tuple[bool, Optional[str]]:
        logger.info(f"{self.log_prefix} 执行智能发布公告动作")
        has_permission, permission_error = self._check_group_permission()
        content = self.action_data.get("content")
        image = self.action_data.get("image", "")
        reason = self.action_data.get("reason", "管理员操作")
        
        if not content:
            error_msg = "公告内容不能为空"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("没有指定公告内容呢~")
            return False, error_msg
            
        # 验证公告内容长度
        if len(content) > 1000:
            error_msg = "公告内容过长，不能超过1000个字符"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("公告内容太长啦，不能超过1000个字符哦~")
            return False, error_msg
            
        message = self._get_template_message(content, reason)
        if not has_permission:
            logger.warning(f"{self.log_prefix} 权限检查失败: {permission_error}")
            result_status, result_message = await generator_api.rewrite_reply(
                chat_stream=self.chat_stream,
                reply_data={
                    "raw_reply": "我想发布一个公告：{content}，但是我没有权限",
                    "reason": "表达自己没有在这个群发布公告的能力",
                },
            )
            if result_status:
                for reply_seg in result_message:
                    data = reply_seg[1]
                    await self.send_text(data)
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"尝试发布公告：{content}，但是没有权限，无法操作",
                action_done=True,
            )
            return False, permission_error
        result_status, result_message = await generator_api.rewrite_reply(
            chat_stream=self.chat_stream,
            reply_data={
                "raw_reply": message,
                "reason": reason,
            },
        )
        if result_status:
            for reply_seg in result_message:
                data = reply_seg[1]
                await self.send_text(data)
        # 发送群聊发布公告命令（使用 NapCat API）
        from src.plugin_system.apis import send_api
        group_id = self.group_id if hasattr(self, "group_id") else None
        platform = self.platform if hasattr(self, "platform") else "qq"
        if not group_id:
            error_msg = "无法获取群聊ID"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("执行发布公告动作失败（群ID缺失）")
            return False, error_msg
        # Napcat API 发布公告实现
        import httpx
        napcat_api = "http://127.0.0.1:3000/_send_group_notice"
        payload = {
            "group_id": str(group_id),
            "content": content,
            "image": image
        }
        logger.info(f"{self.log_prefix} Napcat发布公告API请求: {napcat_api}, payload={payload}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(napcat_api, json=payload, timeout=5)
            logger.info(f"{self.log_prefix} Napcat发布公告API响应: status={response.status_code}, body={response.text}")
            if response.status_code == 200:
                resp_json = response.json()
                if resp_json.get("status") == "ok" and resp_json.get("retcode") == 0:
                    logger.info(f"{self.log_prefix} 成功发布公告，群: {group_id}，内容: {content}")
                    await self.store_action_info(
                        action_build_into_prompt=True,
                        action_prompt_display=f"尝试发布公告：{content}，原因：{reason}",
                        action_done=True,
                    )
                    return True, f"成功发布公告"
                else:
                    error_msg = f"Napcat API返回失败: {resp_json}"
                    logger.error(f"{self.log_prefix} {error_msg}")
                    await self.send_text("执行发布公告动作失败（API返回失败）")
                    return False, error_msg
            else:
                error_msg = f"Napcat API请求失败: HTTP {response.status_code}"
                logger.error(f"{self.log_prefix} {error_msg}")
                await self.send_text("执行发布公告动作失败（API请求失败）")
                return False, error_msg
        except Exception as e:
            error_msg = f"Napcat API请求异常: {e}"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("执行发布公告动作失败（API异常）")
            return False, error_msg

    def _get_template_message(self, content: str, reason: str) -> str:
        templates = self.get_config("notice.templates")
        template = random.choice(templates)
        # 截取部分内容用于显示
        display_content = content[:50] + "..." if len(content) > 50 else content
        return template.format(content=display_content, reason=reason)

# ===== Command组件 =====

class SendGroupNoticeCommand(BaseCommand):
    """发布公告命令 - 手动执行发布公告操作"""
    command_name = "send_group_notice_command"
    command_description = "发布公告命令，手动执行发布公告操作"
    command_pattern = r"^/send_notice\s+(?P<content>.+?)(?:\s+--image=(?P<image>\S+))?(?:\s+(?P<reason>.+))?$"
    command_help = "发布公告，用法：/send_notice <公告内容> [--image=图片链接] [理由]"
    command_examples = ["/send_notice 重要通知：明天维护", "/send_notice 活动安排 --image=https://example.com/image.jpg 活动宣传"]
    intercept_message = True

    def _check_user_permission(self) -> Tuple[bool, Optional[str]]:
        chat_stream = self.message.chat_stream
        if not chat_stream:
            return False, "无法获取聊天流信息"
        current_platform = chat_stream.platform
        current_user_id = str(chat_stream.user_info.user_id)
        allowed_users = self.get_config("permissions.allowed_users", [])
        if not allowed_users:
            logger.info(f"{self.log_prefix} 用户权限未配置，允许所有用户使用发布公告命令")
            return True, None
        current_user_key = f"{current_platform}:{current_user_id}"
        for allowed_user in allowed_users:
            if allowed_user == current_user_key:
                logger.info(f"{self.log_prefix} 用户 {current_user_key} 有发布公告命令权限")
                return True, None
        logger.warning(f"{self.log_prefix} 用户 {current_user_key} 没有发布公告命令权限")
        return False, "你没有使用发布公告命令的权限"

    async def execute(self) -> Tuple[bool, Optional[str]]:
        try:
            has_permission, permission_error = self._check_user_permission()
            if not has_permission:
                logger.error(f"{self.log_prefix} 权限检查失败: {permission_error}")
                await self.send_text(f"❌ {permission_error}")
                return False, permission_error
            content = self.matched_groups.get("content")
            image = self.matched_groups.get("image", "")
            reason = self.matched_groups.get("reason", "管理员操作")
                
            if not content:
                await self.send_text("❌ 命令参数不完整，请检查格式")
                return False, "参数不完整"
                
            # 验证公告内容长度
            if len(content) > 1000:
                await self.send_text("❌ 公告内容太长啦，不能超过1000个字符哦~")
                return False, "公告内容过长"
                
            logger.info(f"{self.log_prefix} 执行发布公告命令: 内容: {content}")
            # 发送群聊发布公告命令（使用 NapCat API）
            from src.plugin_system.apis import send_api
            group_id = self.message.chat_stream.group_info.group_id if self.message.chat_stream and self.message.chat_stream.group_info else None
            platform = self.message.chat_stream.platform if self.message.chat_stream else "qq"
            if not group_id:
                await self.send_text("❌ 无法获取群聊ID")
                return False, "群聊ID缺失"
            # Napcat API 发布公告实现
            import httpx
            napcat_api = "http://127.0.0.1:3000/_send_group_notice"
            payload = {
                "group_id": str(group_id),
                "content": content,
                "image": image
            }
            logger.info(f"{self.log_prefix} Napcat发布公告API请求: {napcat_api}, payload={payload}")
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(napcat_api, json=payload, timeout=5)
                logger.info(f"{self.log_prefix} Napcat发布公告API响应: status={response.status_code}, body={response.text}")
                if response.status_code == 200:
                    resp_json = response.json()
                    if resp_json.get("status") == "ok" and resp_json.get("retcode") == 0:
                        message = self._get_template_message(content, reason)
                        await self.send_text(message)
                        logger.info(f"{self.log_prefix} 成功发布公告，群: {group_id}，内容: {content}")
                        return True, f"成功发布公告"
                    else:
                        error_msg = f"Napcat API返回失败: {resp_json}"
                        logger.error(f"{self.log_prefix} {error_msg}")
                        await self.send_text("❌ 发送发布公告命令失败（API返回失败）")
                        return False, error_msg
                else:
                    error_msg = f"Napcat API请求失败: HTTP {response.status_code}"
                    logger.error(f"{self.log_prefix} {error_msg}")
                    await self.send_text("❌ 发送发布公告命令失败（API请求失败）")
                    return False, error_msg
            except Exception as e:
                error_msg = f"Napcat API请求异常: {e}"
                logger.error(f"{self.log_prefix} {error_msg}")
                await self.send_text("❌ 发送发布公告命令失败（API异常）")
                return False, error_msg
        except Exception as e:
            logger.error(f"{self.log_prefix} 发布公告命令执行失败: {e}")
            await self.send_text(f"❌ 发布公告命令错误: {str(e)}")
            return False, str(e)

    def _get_template_message(self, content: str, reason: str) -> str:
        templates = self.get_config("notice.templates")
        template = random.choice(templates)
        # 截取部分内容用于显示
        display_content = content[:50] + "..." if len(content) > 50 else content
        return template.format(content=display_content, reason=reason)

# ===== 插件主类 =====

@register_plugin
class SendGroupNoticePlugin(BasePlugin):
    """发布公告插件
    提供智能发布公告功能：
    - 智能发布公告Action：基于LLM判断是否需要发布公告（支持群组权限控制）
    - 发布公告命令Command：手动执行发布公告操作（支持用户权限控制）
    """
    plugin_name = "send_group_notice_plugin"
    enable_plugin = True
    config_file_name = "config.toml"
    config_section_descriptions = {
        "plugin": "插件基本信息配置",
        "components": "组件启用控制",
        "permissions": "权限管理配置",
        "notice": "核心发布公告功能配置",
        "smart_notice": "智能发布公告Action的专属配置",
        "notice_command": "发布公告命令Command的专属配置",
        "logging": "日志记录相关配置",
    }
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="0.0.1", description="配置文件版本"),
        },
        "components": {
            "enable_smart_notice": ConfigField(type=bool, default=True, description="是否启用智能发布公告Action"),
            "enable_notice_command": ConfigField(
                type=bool, default=False, description="是否启用发布公告命令Command（调试用）"
            ),
        },
        "permissions": {
            "allowed_users": ConfigField(
                type=list,
                default=[],
                description="允许使用发布公告命令的用户列表，格式：['platform:user_id']，如['qq:123456789']。空列表表示不启用权限控制",
            ),
            "allowed_groups": ConfigField(
                type=list,
                default=[],
                description="允许使用发布公告动作的群组列表，格式：['platform:group_id']，如['qq:987654321']。空列表表示不启用权限控制",
            ),
        },
        "notice": {
            "enable_message_formatting": ConfigField(
                type=bool, default=True, description="是否启用人性化的消息显示"
            ),
            "log_notice_history": ConfigField(type=bool, default=True, description="是否记录发布公告历史（未来功能）"),
            "templates": ConfigField(
                type=list,
                default=[
                    "好的，已发布群公告：{content}，理由：{reason}",
                    "收到，发布公告：{content}，因为{reason}",
                    "明白了，已发布公告：{content}，原因是{reason}",
                    "已发布群公告：{content}，理由：{reason}",
                    "公告发布完成：{content}，原因：{reason}",
                ],
                description="成功发布公告后发送的随机消息模板",
            ),
            "error_messages": ConfigField(
                type=list,
                default=[
                    "没有指定公告内容呢~",
                    "公告内容太长啦，不能超过1000个字符哦~",
                    "发布公告时出现问题~",
                ],
                description="执行发布公告过程中发生错误时发送的随机消息模板",
            ),
        },
        "smart_notice": {
            "strict_mode": ConfigField(type=bool, default=True, description="LLM判定的严格模式"),
            "keyword_sensitivity": ConfigField(
                type=str, default="normal", description="关键词激活的敏感度", choices=["low", "normal", "high"]
            ),
            "allow_parallel": ConfigField(type=bool, default=False, description="是否允许并行执行（暂未启用）"),
        },
        "notice_command": {
            "max_batch_size": ConfigField(type=int, default=5, description="最大批量发布公告数量（未来功能）"),
            "cooldown_seconds": ConfigField(type=int, default=3, description="命令冷却时间（秒）"),
        },
        "logging": {
            "level": ConfigField(
                type=str, default="INFO", description="日志记录级别", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
            ),
            "prefix": ConfigField(type=str, default="[SendGroupNoticePlugin]", description="日志记录前缀"),
            "include_user_info": ConfigField(type=bool, default=True, description="日志中是否包含用户信息"),
            "include_action_info": ConfigField(type=bool, default=True, description="日志中是否包含操作信息"),
        },
    }
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        enable_smart_notice = self.get_config("components.enable_smart_notice", True)
        enable_notice_command = self.get_config("components.enable_notice_command", True)
        components = []
        if enable_smart_notice:
            components.append((SendGroupNoticeAction.get_action_info(), SendGroupNoticeAction))
        if enable_notice_command:
            components.append((SendGroupNoticeCommand.get_command_info(), SendGroupNoticeCommand))
        return components
