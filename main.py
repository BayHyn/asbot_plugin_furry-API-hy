from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import httpx
import asyncio
import time
from collections import deque
from typing import Dict, List, Optional, Any, Union

@register("asbot_plugin_furry-API-hy", "furryhm", "调用趣绮梦云黑API的群黑云查询踢出还有进群自动检测黑云有问题自动踢出的插件", "3.0.0")
class QimengYunheiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 存储待踢出的云黑成员列表
        self.pending_kick_members: Dict[str, List[Dict[str, str]]] = {}
        # 记录每个群组的最后扫描时间
        self.last_scan_time: Dict[str, float] = {}
        # 记录每个群组的自动清理时间阈值（秒），默认300秒（5分钟）
        self.cleanup_threshold: Dict[str, int] = {}
        # API请求频率限制相关
        self.request_timestamps: deque = deque()
        self.max_requests = 20
        self.time_window = 5  # 秒
        # 自动清理任务
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _rate_limited_request(self, url: str) -> Dict[str, Any]:
        """
        带频率限制的API请求
        限制为20次请求/5秒
        """
        current_time = time.time()
        
        # 清除时间窗口外的请求记录
        while self.request_timestamps and self.request_timestamps[0] < current_time - self.time_window:
            self.request_timestamps.popleft()
        
        # 如果当前窗口内的请求数已达到上限，则等待
        if len(self.request_timestamps) >= self.max_requests:
            oldest_request_time = self.request_timestamps[0]
            sleep_time = self.time_window - (current_time - oldest_request_time)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                # 再次清理过期的请求记录
                current_time = time.time()
                while self.request_timestamps and self.request_timestamps[0] < current_time - self.time_window:
                    self.request_timestamps.popleft()
        
        # 记录当前请求时间
        self.request_timestamps.append(current_time)
        
        # 发起请求
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=10)
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as e:
                logger.error(f"API请求失败: {str(e)}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"API返回错误状态: {e.response.status_code}")
                raise

    async def _periodic_cleanup(self) -> None:
        """
        定时自动清理任务
        定期清理过期的请求记录和待踢出成员列表
        """
        while True:
            try:
                # 每30秒执行一次清理
                await asyncio.sleep(30)
                
                # 清理过期的请求记录
                current_time = time.time()
                while self.request_timestamps and self.request_timestamps[0] < current_time - self.time_window:
                    self.request_timestamps.popleft()
                
                # 清理超过设定时间未处理的待踢出成员列表
                expired_groups = []
                for group_id, timestamp in self.last_scan_time.items():
                    # 获取该群组的清理阈值，默认为300秒（5分钟）
                    threshold = self.cleanup_threshold.get(group_id, 300)
                    if current_time - timestamp > threshold:
                        expired_groups.append(group_id)
                
                for group_id in expired_groups:
                    if group_id in self.pending_kick_members:
                        del self.pending_kick_members[group_id]
                        logger.info(f"已清理群组 {group_id} 的过期待踢出成员列表")
                    if group_id in self.last_scan_time:
                        del self.last_scan_time[group_id]
                    # 不删除cleanup_threshold中的记录，因为可能需要保留用户设置
                    
            except Exception as e:
                logger.error(f"定时清理任务出错: {str(e)}")

    def _is_yunhei_member(self, yunhei_info: Dict[str, Any]) -> bool:
        """
        判断是否为云黑成员
        """
        return str(yunhei_info.get('yh', '')).lower() == 'true' if yunhei_info.get('yh') is not None else False

    async def _check_member_yunhei_status(self, member_id: Union[str, int], api_key: str) -> Optional[Dict[str, str]]:
        """
        检查单个成员的云黑状态
        """
        api_url = f"https://fz.qimeng.fun/OpenAPI/all_f.php?id={member_id}&key={api_key}"
        try:
            data = await self._rate_limited_request(api_url)
            
            # 解析返回数据
            if data.get("info"):
                info_list = data.get("info", [{}])[0].get("info", [])
                if len(info_list) >= 3:
                    yunhei_info = info_list[2]  # 云黑记录信息
                    # 检查是否为云黑成员
                    if self._is_yunhei_member(yunhei_info):
                        return {
                            'id': str(member_id),
                            'reason': yunhei_info.get('note', '无说明'),
                            'type': yunhei_info.get('type', '未知'),
                            'admin': yunhei_info.get('admin', '未知'),
                            'level': yunhei_info.get('level', '无'),
                            'date': yunhei_info.get('date', '无记录')
                        }
        except Exception as e:
            logger.error(f"查询成员 {member_id} 云黑状态时出错: {str(e)}")
        return None

    async def _kick_member(self, group_id: Union[str, int], member_id: Union[str, int], reason: str = "", type_: str = "", date: str = "") -> bool:
        """
        踢出单个成员
        """
        try:
            await self.context.bot.set_group_kick(
                group_id=int(group_id), 
                user_id=int(member_id), 
                reject_add_request=False
            )
            
            logger.info(f"已踢出云黑成员: {member_id}，原因: {reason}，类型: {type_}，日期: {date}")
            return True
        except Exception as e:
            logger.error(f"踢出成员 {member_id} 时出错: {str(e)}")
            return False

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_group_add(self, event: AstrMessageEvent) -> None:
        """
        处理群成员增加事件
        """
        # 检查事件类型是否为群成员增加
        raw_message = event.message_obj.raw_message
        if not (raw_message.get('post_type') == 'notice' and raw_message.get('notice_type') == 'group_increase'):
            return
            
        # 获取群组ID和新成员ID
        group_id = raw_message.get('group_id')
        user_id = raw_message.get('user_id')
        
        # 检查API Key是否配置
        api_key = self.config.get("api_key", "")
        if not api_key:
            logger.warning("API Key未配置，无法检测新成员云黑状态")
            return
            
        try:
            # 检查成员是否为云黑成员
            blacklisted_member = await self._check_member_yunhei_status(user_id, api_key)
            
            if blacklisted_member:
                # 踢出成员
                success = await self._kick_member(
                    group_id, 
                    user_id, 
                    blacklisted_member['reason'], 
                    blacklisted_member['type'], 
                    blacklisted_member['date']
                )
                
                if success:
                    # 发送通知消息
                    kick_message = (f"检测到云黑成员 {user_id} 已被自动踢出\n"
                                  f"原因: {blacklisted_member['reason']}\n"
                                  f"类型: {blacklisted_member['type']}\n"
                                  f"日期: {blacklisted_member['date']}")
                    await self.context.bot.send_message(group_id=int(group_id), message=kick_message)
                        
        except Exception as e:
            logger.error(f"检测新成员 {user_id} 云黑状态时出错: {str(e)}")

    @filter.command("扫描云黑成员", "扫描所有群云黑成员，显示云黑成员列表")
    async def scan_group_members(self, event: AstrMessageEvent) -> None:
        # 检查是否在群聊中使用该命令
        if not event.get_group_id():
            yield event.plain_result("该命令只能在群聊中使用")
            return
            
        # 检查API Key是否配置
        api_key = self.config.get("api_key", "")
        if not api_key:
            yield event.plain_result("请先在插件配置中填写申请的API Key")
            return

        yield event.plain_result("开始扫描群成员云黑信息...")
        
        try:
            # 获取群成员列表
            group_member_list = await self.context.bot.get_group_member_list(
                group_id=int(event.get_group_id()), 
                no_cache=True
            )
            # 提取成员QQ号列表
            group_members = [str(member['user_id']) for member in group_member_list]
        except Exception as e:
            logger.error(f"获取群成员列表时出错: {str(e)}")
            yield event.plain_result("获取群成员列表失败")
            return
        
        if not group_members:
            yield event.plain_result("无法获取群成员列表")
            return
            
        # 并发检查所有成员的云黑状态
        tasks = [self._check_member_yunhei_status(member_id, api_key) for member_id in group_members]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        blacklisted_members = [result for result in results if result and not isinstance(result, Exception)]
        
        if not blacklisted_members:
            yield event.plain_result("扫描完成！未发现云黑成员。")
            return
            
        # 保存待踢出成员列表
        group_id = event.get_group_id()
        self.pending_kick_members[group_id] = blacklisted_members
        self.last_scan_time[group_id] = time.time()
        
        # 构建云黑成员列表信息
        result = f"扫描完成！发现 {len(blacklisted_members)} 名云黑成员：\n\n"
        for i, member in enumerate(blacklisted_members, 1):
            result += f"{i}. 用户ID: {member['id']}\n"
            result += f"   原因: {member['reason']}\n"
            result += f"   类型: {member['type']}\n"
            result += f"   管理员: {member['admin']}\n"
            result += f"   等级: {member['level']}\n"
            result += f"   日期: {member['date']}\n\n"
            
        result += "如需踢出以上云黑成员，请在30秒内发送命令：确认踢出"
        yield event.plain_result(result)

    @filter.command("确认踢出", "确认踢出云黑成员")
    async def confirm_kick_members(self, event: AstrMessageEvent) -> None:
        # 检查是否在群聊中使用该命令
        if not event.get_group_id():
            yield event.plain_result("该命令只能在群聊中使用")
            return
            
        group_id = event.get_group_id()
        
        # 检查是否有待踢出的成员
        if group_id not in self.pending_kick_members or not self.pending_kick_members[group_id]:
            yield event.plain_result("当前没有待踢出的云黑成员。请先执行「防撤回 查看」命令。")
            return
            
        blacklisted_members = self.pending_kick_members[group_id]
        
        # 并发踢出所有云黑成员
        tasks = [self._kick_member(group_id, member['id'], member.get('reason', ''), member.get('type', ''), member.get('date', '')) for member in blacklisted_members]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        kicked_count = sum(1 for result in results if result is True and isinstance(result, bool))
        
        # 清除已处理的待踢出成员列表
        if group_id in self.pending_kick_members:
            del self.pending_kick_members[group_id]
        if group_id in self.last_scan_time:
            del self.last_scan_time[group_id]
        
        result = f"已完成踢出操作！\n成功踢出云黑成员数：{kicked_count}\n失败数：{len(blacklisted_members) - kicked_count}"
        yield event.plain_result(result)

    @filter.command("设置清理时间", "设置当前群组的自动清理时间阈值（秒）")
    async def set_cleanup_threshold(self, event: AstrMessageEvent) -> None:
        # 检查是否在群聊中使用该命令
        if not event.get_group_id():
            yield event.plain_result("该命令只能在群聊中使用")
            return
            
        group_id = event.get_group_id()
        params = event.get_message().split()
        
        # 检查是否有提供时间参数
        if len(params) < 2:
            current_threshold = self.cleanup_threshold.get(group_id, 300)
            yield event.plain_result(f"当前群组自动清理时间阈值为 {current_threshold} 秒\n用法: 设置清理时间 <秒数>")
            return
            
        try:
            threshold = int(params[1])
            if threshold < 10:
                yield event.plain_result("清理时间阈值不能少于10秒")
                return
            if threshold > 3600:
                yield event.plain_result("清理时间阈值不能超过3600秒（1小时）")
                return
                
            self.cleanup_threshold[group_id] = threshold
            yield event.plain_result(f"已设置当前群组自动清理时间阈值为 {threshold} 秒")
            
        except ValueError:
            yield event.plain_result("参数错误，请输入有效的秒数\n用法: 设置清理时间 <秒数>")

    async def terminate(self) -> None:
        """
        插件终止时的清理工作
        """
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass