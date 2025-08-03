"""
禁言插件

提供智能禁言功能的群聊管理插件。

功能特性：
- 智能LLM判定：根据聊天内容智能判断是否需要禁言
- 模板化消息：支持自定义禁言提示消息
- 参数验证：完整的输入参数验证和错误处理
- 配置文件支持：所有设置可通过配置文件调整
- 权限管理：支持用户权限和群组权限控制

包含组件：
- 智能禁言Action - 基于LLM判断是否需要禁言（支持群组权限控制）
- 禁言命令Command - 手动执行禁言操作（支持用户权限控制）
"""

from typing import List, Tuple, Type, Optional, Union
import random

from src.plugin_system import BasePlugin, register_plugin
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo, ActionActivationType, ChatMode, CommandInfo
from src.plugin_system.base.config_types import ConfigField
from src.common.logger import get_logger
from src.plugin_system.apis import person_api, generator_api

logger = get_logger("mute_user_plugin")

# ===== Action组件 =====

class MuteUserAction(BaseAction):
    """智能禁言Action - 基于LLM智能判断是否需要禁言"""

    focus_activation_type = ActionActivationType.LLM_JUDGE
    normal_activation_type = ActionActivationType.KEYWORD
    mode_enable = ChatMode.ALL
    parallel_action = True

    action_name = "mute_user"
    action_description = "智能禁言系统，基于LLM判断是否需要禁言/解除禁言"

    activation_keywords = ["禁言", "mute"]
    keyword_case_sensitive = False

    llm_judge_prompt = """
禁言/解除禁言的严格条件：

使用禁言的情况：
1. 群主或管理员明确要求禁言某用户
2. 用户出现严重扰乱群聊秩序的行为（如刷屏、恶意挑衅等）
3. 用户发布违法违规内容需要及时制止
4. 用户被多次警告无效后需要临时禁言

使用解除禁言的情况：
1. 群主或管理员明确要求解除某用户禁言
2. 管理员误操作禁言需要解除
3. 用户已认识到错误并请求解除禁言

绝对不要使用的情况：
1. 没有明确授权的情况下擅自禁言/解除禁言用户
2. 对正常发言的用户随意禁言
"""

    action_parameters = {
        "user_id": "需要禁言/解除禁言的用户ID或用户名，仔细思考不要弄错对象，必填",
        "duration": "禁言时长（秒），0表示解除禁言，范围：0-2592000，必填",
    }

    action_require = [
        "当群主或管理员明确要求禁言/解除禁言某用户时使用",
        "当用户出现严重扰乱群聊秩序行为需要禁言时使用",
        "当用户已认识到错误并请求解除禁言时使用",
    ]

    associated_types = ["text", "command"]

    def _check_group_permission(self) -> Tuple[bool, Optional[str]]:
        if not self.is_group:
            return False, "禁言动作只能在群聊中使用"
        allowed_groups = self.get_config("permissions.allowed_groups", [])
        if not allowed_groups:
            logger.info(f"{self.log_prefix} 群组权限未配置，允许所有群使用禁言动作")
            return True, None
        current_group_key = f"{self.platform}:{self.group_id}"
        for allowed_group in allowed_groups:
            if allowed_group == current_group_key:
                logger.info(f"{self.log_prefix} 群组 {current_group_key} 有禁言动作权限")
                return True, None
        logger.warning(f"{self.log_prefix} 群组 {current_group_key} 没有禁言动作权限")
        return False, "当前群组没有使用禁言动作的权限"

    async def execute(self) -> Tuple[bool, Optional[str]]:
        logger.info(f"{self.log_prefix} 执行智能禁言动作")
        has_permission, permission_error = self._check_group_permission()
        user_id_or_name = self.action_data.get("user_id")
        duration = self.action_data.get("duration", 0)
        reason = self.action_data.get("reason", "管理员操作")

        if not user_id_or_name:
            error_msg = "用户不能为空"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("没有指定要禁言的用户呢~")
            return False, error_msg

        user_id = None
        # 检查 user_id_or_name 是否是纯数字ID
        user_id_or_name_str = str(user_id_or_name)
        if user_id_or_name_str.isdigit():
            user_id = user_id_or_name_str
        else:
            # 如果不是数字，则认为是用户名，需要查询ID
            logger.info(f"{self.log_prefix} 用户 '{user_id_or_name_str}' 不是数字ID，尝试作为用户名查询...")
            person_id = person_api.get_person_id_by_name(user_id_or_name_str)
            if person_id:
                # 从 person_id 获取真实的 user_id
                real_user_id = await person_api.get_person_value(person_id, "user_id")
                if real_user_id:
                    user_id = str(real_user_id)
                    logger.info(f"{self.log_prefix} 成功将用户名 '{user_id_or_name_str}' 解析为 user_id: {user_id}")
                else:
                    logger.warning(f"{self.log_prefix} 找到了 person_id 但无法获取 user_id，用户名: '{user_id_or_name_str}'")
            else:
                logger.warning(f"{self.log_prefix} 无法通过用户名 '{user_id_or_name_str}' 找到用户")

        if not user_id:
            error_msg = f"无法解析用户 '{user_id_or_name_str}'"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text(f"找不到用户 '{user_id_or_name_str}' 呢~")
            return False, error_msg

        # 修改开始：在这里调用修正后的 _get_template_message
        message = self._get_template_message(user_id, duration, reason)
        # 修改结束

        if not has_permission:
            logger.warning(f"{self.log_prefix} 权限检查失败: {permission_error}")
            result_status, result_message = await generator_api.rewrite_reply(
                chat_stream=self.chat_stream,
                reply_data={
                    "raw_reply": "我想{'禁言' if duration > 0 else '解除禁言'}用户 {user_id}，但是我没有权限",
                    "reason": "表达自己没有在这个群禁言用户的能力",
                },
            )
            if result_status:
                for reply_seg in result_message:
                    data = reply_seg[1]
                    await self.send_text(data)
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"尝试{'禁言' if duration > 0 else '解除禁言'}用户 {user_id}，但是没有权限，无法操作",
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
        # 发送群聊禁言命令（使用 NapCat API）
        from src.plugin_system.apis import send_api
        group_id = self.group_id if hasattr(self, "group_id") else None
        platform = self.platform if hasattr(self, "platform") else "qq"
        if not group_id:
            error_msg = "无法获取群聊ID"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("执行禁言动作失败（群ID缺失）")
            return False, error_msg
        # Napcat API 禁言实现
        import httpx
        napcat_api = "http://127.0.0.1:3000/set_group_ban"
        payload = {
            "group_id": str(group_id),
            "user_id": str(user_id),
            "duration": int(duration)
        }
        logger.info(f"{self.log_prefix} Napcat禁言API请求: {napcat_api}, payload={payload}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(napcat_api, json=payload, timeout=5)
            logger.info(f"{self.log_prefix} Napcat禁言API响应: status={response.status_code}, body={response.text}")
            if response.status_code == 200:
                resp_json = response.json()
                if resp_json.get("status") == "ok" and resp_json.get("retcode") == 0:
                    logger.info(f"{self.log_prefix} 成功{'禁言' if duration > 0 else '解除禁言'}用户 {user_id}，群: {group_id}")
                    await self.store_action_info(
                        action_build_into_prompt=True,
                        action_prompt_display=f"尝试{'禁言' if duration > 0 else '解除禁言'}用户 {user_id}，原因：{reason}",
                        action_done=True,
                    )
                    return True, f"成功{'禁言' if duration > 0 else '解除禁言'}用户 {user_id}"
                else:
                    error_msg = f"Napcat API返回失败: {resp_json}"
                    logger.error(f"{self.log_prefix} {error_msg}")
                    await self.send_text("执行禁言动作失败（API返回失败）")
                    return False, error_msg
            else:
                error_msg = f"Napcat API请求失败: HTTP {response.status_code}"
                logger.error(f"{self.log_prefix} {error_msg}")
                await self.send_text("执行禁言动作失败（API请求失败）")
                return False, error_msg
        except Exception as e:
            error_msg = f"Napcat API请求异常: {e}"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("执行禁言动作失败（API异常）")
            return False, error_msg

    # ===== 修改开始：完全重写此函数以增强健壮性和修复BUG =====
    def _get_template_message(self, user_id: str, duration: int, reason: str) -> str:
        """
        根据操作获取并格式化回复消息模板。
        该函数经过重写，以修复配置读取错误和增强代码健壮性。
        """
        # 1. 先获取包含 mute 和 unmute 两个列表的整个字典
        all_templates = self.get_config("mute.templates")
        
        # 2. 根据 duration 判断是禁言还是解禁，并获取对应的模板列表
        if duration > 0:
            template_list = all_templates.get("mute") if all_templates else None
            action_text = "禁言"
        else:
            template_list = all_templates.get("unmute") if all_templates else None
            action_text = "解除禁言"

        # 3. 健壮性检查：如果找不到模板列表（配置错误或缺失），则返回一个安全的默认消息
        if not template_list:
            logger.warning(f"{self.log_prefix} 未在配置文件中找到 {action_text} 的消息模板 (mute.templates.{'mute' if duration > 0 else 'unmute'})，将使用默认回复。")
            return f"操作已执行：对用户 {user_id} {action_text}，时长：{duration}秒，原因：{reason}"
            
        # 4. 从列表中随机选择一个模板
        template = random.choice(template_list)
        
        # 5. 为了兼容模板中可能存在的不同变量（如 user_id, target, user_name 等），
        #    创建一个上下文词典，使用 format_map 安全地格式化字符串。
        context = {
            "user_id": user_id,
            "target": user_id,  # 别名，兼容
            "user_name": user_id, # 别名，兼容
            "duration": f"{duration}秒",
            "reason": reason,
        }
        
        try:
            return template.format_map(context)
        except KeyError as e:
            # 如果模板中的变量在 context 中不存在，也能优雅处理
            logger.error(f"{self.log_prefix} 格式化消息模板时出错，缺少键：{e}。模板：'{template}'")
            return f"操作已执行，但消息模板格式化失败。用户：{user_id}，原因：{reason}"
    # ===== 修改结束 =====


# ===== Command组件 =====

class MuteUserCommand(BaseCommand):
    """禁言命令 - 手动执行禁言操作"""
    command_name = "mute_user_command"
    description = "禁言命令，手动执行禁言/解除禁言操作"
    # 修改了正则表达式，使 command 捕获 mute 或 unmute
    command_pattern = r"^/(?P<command>mute|unmute)\s+(?P<user_id>\d+)(?:\s+(?P<duration>\d+))?(?:\s+(?P<reason>.+))?$"
    intercept_message = True

    def _check_user_permission(self) -> Tuple[bool, Optional[str]]:
        chat_stream = self.message.chat_stream
        if not chat_stream:
            return False, "无法获取聊天流信息"
        current_platform = chat_stream.platform
        current_user_id = str(chat_stream.user_info.user_id)
        allowed_users = self.get_config("permissions.allowed_users", [])
        if not allowed_users:
            logger.info(f"{self.log_prefix} 用户权限未配置，允许所有用户使用禁言命令")
            return True, None
        current_user_key = f"{current_platform}:{current_user_id}"
        for allowed_user in allowed_users:
            if allowed_user == current_user_key:
                logger.info(f"{self.log_prefix} 用户 {current_user_key} 有禁言命令权限")
                return True, None
        logger.warning(f"{self.log_prefix} 用户 {current_user_key} 没有禁言命令权限")
        return False, "你没有使用禁言命令的权限"

    async def execute(self) -> Tuple[bool, Optional[str]]:
        try:
            has_permission, permission_error = self._check_user_permission()
            if not has_permission:
                logger.error(f"{self.log_prefix} 权限检查失败: {permission_error}")
                await self.send_text(f"❌ {permission_error}")
                return False, permission_error
                
            command = self.matched_groups.get("command")
            user_id = self.matched_groups.get("user_id")
            # 如果 duration 未提供，则根据命令类型（mute/unmute）设置默认值
            duration_str = self.matched_groups.get("duration")
            if command == "mute":
                duration = int(duration_str) if duration_str else self.get_config("mute_command.default_duration", 600)
            else: # command == "unmute"
                duration = 0
            reason = self.matched_groups.get("reason", "管理员操作")
            
            if not user_id:
                await self.send_text("❌ 命令参数不完整，请检查格式")
                return False, "参数不完整"
                
            logger.info(f"{self.log_prefix} 执行{'禁言' if command == 'mute' else '解除禁言'}命令: 用户ID: {user_id}")
            # 发送群聊禁言命令（使用 NapCat API）
            from src.plugin_system.apis import send_api
            group_id = self.message.chat_stream.group_info.group_id if self.message.chat_stream and self.message.chat_stream.group_info else None
            platform = self.message.chat_stream.platform if self.message.chat_stream else "qq"
            if not group_id:
                await self.send_text("❌ 无法获取群聊ID")
                return False, "群聊ID缺失"
            # Napcat API 禁言实现
            import httpx
            napcat_api = "http://127.0.0.1:3000/set_group_ban"
            payload = {
                "group_id": str(group_id),
                "user_id": str(user_id),
                "duration": duration
            }
            logger.info(f"{self.log_prefix} Napcat禁言API请求: {napcat_api}, payload={payload}")
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(napcat_api, json=payload, timeout=5)
                logger.info(f"{self.log_prefix} Napcat禁言API响应: status={response.status_code}, body={response.text}")
                if response.status_code == 200:
                    resp_json = response.json()
                    if resp_json.get("status") == "ok" and resp_json.get("retcode") == 0:
                        # 修改开始：在这里调用修正后的 _get_template_message
                        message = self._get_template_message(user_id, duration, reason)
                        # 修改结束
                        await self.send_text(message)
                        logger.info(f"{self.log_prefix} 成功{'禁言' if duration > 0 else '解除禁言'}用户 {user_id}，群: {group_id}")
                        return True, f"成功{'禁言' if duration > 0 else '解除禁言'}用户 {user_id}"
                    else:
                        error_msg = f"Napcat API返回失败: {resp_json}"
                        logger.error(f"{self.log_prefix} {error_msg}")
                        await self.send_text("❌ 发送禁言命令失败（API返回失败）")
                        return False, error_msg
                else:
                    error_msg = f"Napcat API请求失败: HTTP {response.status_code}"
                    logger.error(f"{self.log_prefix} {error_msg}")
                    await self.send_text("❌ 发送禁言命令失败（API请求失败）")
                    return False, error_msg
            except Exception as e:
                error_msg = f"Napcat API请求异常: {e}"
                logger.error(f"{self.log_prefix} {error_msg}")
                await self.send_text("❌ 发送禁言命令失败（API异常）")
                return False, error_msg
        except Exception as e:
            logger.error(f"{self.log_prefix} 禁言命令执行失败: {e}")
            await self.send_text(f"❌ 禁言命令错误: {str(e)}")
            return False, str(e)

    # ===== 修改开始：同样完全重写此函数，与 Action 中的版本保持一致 =====
    def _get_template_message(self, user_id: str, duration: int, reason: str) -> str:
        """
        根据操作获取并格式化回复消息模板。
        该函数经过重写，以修复配置读取错误和增强代码健壮性。
        """
        all_templates = self.get_config("mute.templates")
        
        if duration > 0:
            template_list = all_templates.get("mute") if all_templates else None
            action_text = "禁言"
        else:
            template_list = all_templates.get("unmute") if all_templates else None
            action_text = "解除禁言"

        if not template_list:
            logger.warning(f"{self.log_prefix} 未在配置文件中找到 {action_text} 的消息模板 (mute.templates.{'mute' if duration > 0 else 'unmute'})，将使用默认回复。")
            return f"操作已执行：对用户 {user_id} {action_text}，时长：{duration}秒，原因：{reason}"
            
        template = random.choice(template_list)
        
        context = {
            "user_id": user_id,
            "target": user_id,
            "user_name": user_id,
            "duration": f"{duration}秒",
            "reason": reason,
        }
        
        try:
            return template.format_map(context)
        except KeyError as e:
            logger.error(f"{self.log_prefix} 格式化消息模板时出错，缺少键：{e}。模板：'{template}'")
            return f"操作已执行，但消息模板格式化失败。用户：{user_id}，原因：{reason}"
    # ===== 修改结束 =====

# ===== 插件主类 =====

@register_plugin
class MuteUserPlugin(BasePlugin):
    """禁言插件
    提供智能禁言功能：
    - 智能禁言Action：基于LLM判断是否需要禁言（支持群组权限控制）
    - 禁言命令Command：手动执行禁言操作（支持用户权限控制）
    """
    plugin_name = "mute_user_plugin"
    enable_plugin = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name = "config.toml"
    config_section_descriptions = {
        "plugin": "插件基本信息配置",
        "components": "组件启用控制",
        "permissions": "权限管理配置",
        "mute": "核心禁言功能配置",
        "smart_mute": "智能禁言Action的专属配置",
        "mute_command": "禁言命令Command的专属配置",
        "logging": "日志记录相关配置",
    }
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="0.0.1", description="配置文件版本"),
        },
        "components": {
            "enable_smart_mute": ConfigField(type=bool, default=True, description="是否启用智能禁言Action"),
            "enable_mute_command": ConfigField(
                type=bool, default=False, description="是否启用禁言命令Command（调试用）"
            ),
        },
        "permissions": {
            "allowed_users": ConfigField(
                type=list,
                default=[],
                description="允许使用禁言命令的用户列表，格式：['platform:user_id']，如['qq:123456789']。空列表表示不启用权限控制",
            ),
            "allowed_groups": ConfigField(
                type=list,
                default=[],
                description="允许使用禁言动作的群组列表，格式：['platform:group_id']，如['qq:987654321']。空列表表示不启用权限控制",
            ),
        },
        "mute": {
            "enable_message_formatting": ConfigField(
                type=bool, default=True, description="是否启用人性化的消息显示"
            ),
            "log_mute_history": ConfigField(type=bool, default=True, description="是否记录禁言历史（未来功能）"),
            # ===== 以下是 config_schema 中正确的 templates 结构 =====
            "templates": ConfigField(
                type=dict,
                default={
                    "mute": [
                        "{target}，你因为{reason}被关进小黑屋{duration}，好好反省一下吧！",
                        "哟，这不是{target}嘛，{reason}的样子真狼狈，禁言套餐{duration}送上！",
                        "根据《麦麦临时约法》，决定对{user_name}处以禁言{duration}的惩罚，原因：{reason}",
                        "已将 {target} 禁言 {duration}，理由：{reason}",
                    ],
                    "unmute": [
                        "好的，已解除用户 {user_id} 的禁言。",
                        "收到，已为用户 {user_id} 解除禁言。",
                        "明白了，用户 {user_id} 的禁言已解除。"
                    ]
                },
                description="成功禁言/解除禁言后发送的随机消息模板",
            ),
            "error_messages": ConfigField(
                type=list,
                default=[
                    "没有指定要禁言的用户ID呢~",
                    "禁言时出现问题~",
                ],
                description="执行禁言过程中发生错误时发送的随机消息模板",
            ),
        },
        "smart_mute": {
            "strict_mode": ConfigField(type=bool, default=True, description="LLM判定的严格模式"),
            "keyword_sensitivity": ConfigField(
                type=str, default="normal", description="关键词激活的敏感度", choices=["low", "normal", "high"]
            ),
            "allow_parallel": ConfigField(type=bool, default=False, description="是否允许并行执行（暂未启用）"),
        },
        "mute_command": {
            "default_duration": ConfigField(type=int, default=600, description="默认禁言时长（秒）"),
            "max_batch_size": ConfigField(type=int, default=5, description="最大批量禁言数量（未来功能）"),
            "cooldown_seconds": ConfigField(type=int, default=3, description="命令冷却时间（秒）"),
        },
        "logging": {
            "level": ConfigField(
                type=str, default="INFO", description="日志记录级别", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
            ),
            "prefix": ConfigField(type=str, default="[MuteUserPlugin]", description="日志记录前缀"),
            "include_user_info": ConfigField(type=bool, default=True, description="日志中是否包含用户信息"),
            "include_action_info": ConfigField(type=bool, default=True, description="日志中是否包含操作信息"),
        },
    }
    
    def get_plugin_components(
        self,
    ) -> List[
        Union[
            Tuple[ComponentInfo, Type[BaseAction]],
            Tuple[CommandInfo, Type[BaseCommand]],
        ]
    ]:
        enable_smart_mute = self.get_config("components.enable_smart_mute", True)
        enable_mute_command = self.get_config("components.enable_mute_command", True)
        components = []
        if enable_smart_mute:
            components.append((MuteUserAction.get_action_info(), MuteUserAction))
        if enable_mute_command:
            components.append((MuteUserCommand.get_command_info(), MuteUserCommand))
        return components
