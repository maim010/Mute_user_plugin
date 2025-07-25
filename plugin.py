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

from typing import List, Tuple, Type, Optional
import random

from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.base_plugin import register_plugin
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo, ActionActivationType, ChatMode
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
    action_description = "智能禁言系统，基于LLM判断是否需要禁言"

    activation_keywords = ["禁言", "mute", "静音", " silence"]
    keyword_case_sensitive = False

    llm_judge_prompt = """
你是有温度的赛博群友，而非机械执法程序。禁言决策需综合聊天语境和群组氛围判断
判定是否需要使用禁言动作
禁言动作的严格条件：

使用禁言的情况：
1. 用户发送违规内容（色情、暴力、政治敏感等）
2. 恶意刷屏或垃圾信息轰炸
3. 严重影响群聊秩序的行为
4. 严重违反群规的行为
5. 恶意攻击他人或群组管理

解除禁言的情况：
1. 用户已认识到错误并改正
2. 管理员决定提前解除禁言
3. 误封情况需要纠正

绝对不要使用的情况：
1. 情绪化表达但无恶意
2. 开玩笑或调侃，除非过分
3. 单纯的意见分歧或争论
4. 对方的权限比你高或相同
"""

    action_parameters = {
        "target": "禁言对象，必填，输入你要禁言的对象的名字，请仔细思考不要弄错对象",
        "duration": "禁言时长（秒），默认3600秒（1小时），范围1-2592000秒（30天）",
        "reason": "禁言理由，可选",
    }

    action_require = [
        "当有人违反群规时使用",
        "当有人发了擦边，或者不当内容时使用",
        "如果某人已经被禁言了，就不要再次操作",
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
        target = self.action_data.get("target")
        duration = self.action_data.get("duration", 3600)  # 默认1小时
        reason = self.action_data.get("reason", "违反群规")
        
        # 验证时长参数
        try:
            duration = int(duration)
            if duration < 1 or duration > 2592000:  # 1秒到30天
                duration = 3600  # 如果超出范围，默认1小时
        except (ValueError, TypeError):
            duration = 3600  # 如果转换失败，默认1小时
            
        if not target:
            error_msg = "禁言目标不能为空"
            logger.error(f"{self.log_prefix} {error_msg}")
            await self.send_text("没有指定禁言对象呢~")
            return False, error_msg
        person_id = person_api.get_person_id_by_name(target)
        user_id = await person_api.get_person_value(person_id, "user_id")
        if not user_id:
            error_msg = f"未找到用户 {target} 的ID"
            await self.send_text(f"找不到 {target} 这个人呢~")
            logger.error(f"{self.log_prefix} {error_msg}")
            return False, error_msg
        message = self._get_template_message(target, duration, reason)
        if not has_permission:
            logger.warning(f"{self.log_prefix} 权限检查失败: {permission_error}")
            result_status, result_message = await generator_api.rewrite_reply(
                chat_stream=self.chat_stream,
                reply_data={
                    "raw_reply": "我想禁言{target}，但是我没有权限",
                    "reason": "表达自己没有在这个群禁言的能力",
                },
            )
            if result_status:
                for reply_seg in result_message:
                    data = reply_seg[1]
                    await self.send_text(data)
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"尝试禁言用户 {target}，但是没有权限，无法操作",
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
                    logger.info(f"{self.log_prefix} 成功禁言 {target}({user_id})，群: {group_id}，时长: {duration}秒")
                    await self.store_action_info(
                        action_build_into_prompt=True,
                        action_prompt_display=f"尝试禁言用户 {target}，时长：{duration}秒，原因：{reason}",
                        action_done=True,
                    )
                    return True, f"成功禁言 {target}"
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

    def _get_template_message(self, target: str, duration: int, reason: str) -> str:
        templates = self.get_config("mute.templates")
        template = random.choice(templates)
        # 将秒转换为更易读的格式
        if duration < 60:
            duration_str = f"{duration}秒"
        elif duration < 3600:
            duration_str = f"{duration // 60}分钟"
        elif duration < 86400:
            duration_str = f"{duration // 3600}小时"
        else:
            duration_str = f"{duration // 86400}天"
        return template.format(target=target, duration=duration_str, reason=reason)

# ===== Command组件 =====

class MuteUserCommand(BaseCommand):
    """禁言命令 - 手动执行禁言操作"""
    command_name = "mute_user_command"
    command_description = "禁言命令，手动执行禁言操作"
    command_pattern = r"^/mute\s+(?P<target>\S+)(?:\s+(?P<duration>\d+))?(?:\s+(?P<reason>.+))?$"
    command_help = "禁言指定用户，用法：/mute <用户名> [时长(秒)] [理由]"
    command_examples = ["/mute 用户名", "/mute 张三 3600 违规", "/mute @某人 1800"]
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
            target = self.matched_groups.get("target")
            duration = self.matched_groups.get("duration", 3600)  # 默认1小时
            reason = self.matched_groups.get("reason", "管理员操作")
            
            # 验证时长参数
            try:
                duration = int(duration)
                if duration < 1 or duration > 2592000:  # 1秒到30天
                    duration = 3600  # 如果超出范围，默认1小时
            except (ValueError, TypeError):
                duration = 3600  # 如果转换失败，默认1小时
                
            if not target:
                await self.send_text("❌ 命令参数不完整，请检查格式")
                return False, "参数不完整"
            person_id = person_api.get_person_id_by_name(target)
            user_id = await person_api.get_person_value(person_id, "user_id")
            if not user_id or user_id == "unknown":
                error_msg = f"未找到用户 {target} 的ID，请输入person_name进行禁言"
                await self.send_text(f"❌ 找不到用户 {target} 的ID，请输入person_name进行禁言，而不是qq号或者昵称")
                logger.error(f"{self.log_prefix} {error_msg}")
                return False, error_msg
            logger.info(f"{self.log_prefix} 执行禁言命令: {target}({user_id})，时长: {duration}秒")
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
                        # 将秒转换为更易读的格式
                        if duration < 60:
                            duration_str = f"{duration}秒"
                        elif duration < 3600:
                            duration_str = f"{duration // 60}分钟"
                        elif duration < 86400:
                            duration_str = f"{duration // 3600}小时"
                        else:
                            duration_str = f"{duration // 86400}天"
                        message = self._get_template_message(target, duration_str, reason)
                        await self.send_text(message)
                        logger.info(f"{self.log_prefix} 成功禁言 {target}({user_id})，群: {group_id}，时长: {duration}秒")
                        return True, f"成功禁言 {target}"
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

    def _get_template_message(self, target: str, duration_str: str, reason: str) -> str:
        templates = self.get_config("mute.templates")
        template = random.choice(templates)
        return template.format(target=target, duration=duration_str, reason=reason)

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
            "templates": ConfigField(
                type=list,
                default=[
                    "好的，已将 {target} 禁言 {duration}，理由：{reason}",
                    "收到，对 {target} 执行禁言 {duration}，因为{reason}",
                    "明白了，禁言 {target} {duration}，原因是{reason}",
                    "已将 {target} 禁言 {duration}，理由：{reason}",
                    "对 {target} 执行禁言 {duration}，因为{reason}",
                ],
                description="成功禁言后发送的随机消息模板",
            ),
            "error_messages": ConfigField(
                type=list,
                default=[
                    "没有指定禁言对象呢~",
                    "找不到 {target} 这个人呢~",
                    "查找用户信息时出现问题~",
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
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        enable_smart_mute = self.get_config("components.enable_smart_mute", True)
        enable_mute_command = self.get_config("components.enable_mute_command", True)
        components = []
        if enable_smart_mute:
            components.append((MuteUserAction.get_action_info(), MuteUserAction))
        if enable_mute_command:
            components.append((MuteUserCommand.get_command_info(), MuteUserCommand))
        return components
