from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as message_components
import httpx
import asyncio
import time
from collections import deque

@register("asbot_plugin_furry-API-hy", "furryhm", "调用趣绮梦云黑API的群黑云查询踢出还有进群自动检测黑云有问题自动踢出的插件", "3.4.0")
class QimengYunheiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 存储待踢出的云黑成员列表
        self.pending_kick_members = {}
        # 群白名单存储 {group_id: [user_id, ...]}
        self.group_whitelist = {}
        # API请求频率限制相关
        self.request_timestamps = deque()
        self.max_requests = 20
        self.time_window = 5  # 秒
        # 创建一个共享的httpx客户端
        self.http_client = httpx.AsyncClient(timeout=10)
        
        # 获取启用云黑检测的群列表
        self.enabled_groups = self.config.get("enabled_groups", [])
        # 获取群组配置，用于存储每个群组的独立配置
        self.group_configs = self.config.get("group_configs", {})
        # 获取启用进群自动检测云黑功能的群白名单
        self.auto_check_whitelist = self.config.get("auto_check_whitelist", [])

    async def _rate_limited_request(self, url):
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
                logger.debug(f"达到频率限制，等待 {sleep_time:.2f} 秒")
                await asyncio.sleep(sleep_time)
                # 再次清理过期的请求记录
                current_time = time.time()
                while self.request_timestamps and self.request_timestamps[0] < current_time - self.time_window:
                    self.request_timestamps.popleft()
        
        # 记录当前请求时间
        self.request_timestamps.append(current_time)
        logger.debug(f"发起API请求，当前窗口请求数: {len(self.request_timestamps)}")
        
        # 发起请求
        response = await self.http_client.get(url)
        response.raise_for_status()
        return response.json()

    async def _batch_check_users(self, user_ids, api_key, batch_size=20):
        """
        批量检查用户云黑状态
        """
        blacklisted_members = []
        
        # 记录开始批量检查
        logger.info(f"开始批量检查 {len(user_ids)} 个用户云黑状态，批量大小: {batch_size}")
        
        # 分批处理用户ID
        for i in range(0, len(user_ids), batch_size):
            batch = user_ids[i:i + batch_size]
            
            logger.debug(f"正在处理批次 {i//batch_size + 1}，包含 {len(batch)} 个用户")
            
            # 为每批用户创建异步任务
            tasks = []
            for user_id in batch:
                api_url = f"https://fz.qimeng.fun/OpenAPI/all_f.php?id={user_id}&key={api_key}"
                task = self._rate_limited_request(api_url)
                tasks.append((task, user_id))
            
            # 并发执行当前批次的任务
            results = await asyncio.gather(*[task for task, _ in tasks], return_exceptions=True)
            
            # 处理结果
            for (result, user_id), task_result in zip(tasks, results):
                try:
                    if isinstance(task_result, Exception):
                        logger.error(f"查询成员 {user_id} 时出错: {str(task_result)}")
                        continue
                    
                    data = task_result
                    # 解析返回数据
                    if data.get("info"):
                        info_list = data.get("info", [])
                        if len(info_list) >= 3:
                            yunhei_info = info_list[2]  # 云黑记录信息
                            
                            # 辅助函数用于判断布尔值
                            def is_true(value):
                                return str(value).lower() == 'true' if value is not None else False
                                
                            # 检查是否为云黑成员
                            if is_true(yunhei_info.get('yh')):
                                # 保存云黑成员信息
                                blacklisted_member = {
                                    'id': user_id,
                                    'reason': yunhei_info.get('note', '无说明'),
                                    'type': yunhei_info.get('type', '未知'),
                                    'admin': yunhei_info.get('admin', '未知'),
                                    'level': yunhei_info.get('level', '无'),
                                    'date': yunhei_info.get('date', '无记录')
                                }
                                blacklisted_members.append(blacklisted_member)
                                logger.info(f"发现云黑成员: {user_id}, 原因: {blacklisted_member['reason']}")
                            else:
                                logger.debug(f"用户 {user_id} 不是云黑成员")
                    else:
                        logger.warning(f"用户 {user_id} 的查询返回空数据")
                except Exception as e:
                    logger.error(f"处理成员 {user_id} 的查询结果时出错: {str(e)}")
                    continue
                    
            # 在批次之间添加小延迟以避免触发API限制
            if i + batch_size < len(user_ids):
                await asyncio.sleep(0.1)
                
        logger.info(f"批量检查完成，共发现 {len(blacklisted_members)} 名云黑成员")
        return blacklisted_members

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_group_add(self, event: AstrMessageEvent):
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
        
        # 记录日志
        logger.info(f"检测到群成员增加事件: 群ID={group_id}, 成员ID={user_id}")
        
        # 统一转换group_id为整数类型用于比较
        group_id_int = int(group_id)
        
        # 检查是否在启用云黑检测的群列表中
        if self.enabled_groups and group_id_int not in self.enabled_groups:
            logger.info(f"群 {group_id} 不在启用云黑检测的群列表中，跳过检测")
            return
            
        # 检查是否在进群自动检测云黑功能的群白名单中
        # 如果配置了白名单且当前群组不在白名单中，则不执行检测
        if self.auto_check_whitelist and group_id_int not in [int(x) for x in self.auto_check_whitelist]:
            logger.info(f"群 {group_id} 不在进群自动检测云黑功能的群白名单中，跳过检测")
            return
        # 如果没有配置白名单，则默认不执行检测（白名单为空时功能关闭）
        elif not self.auto_check_whitelist:
            logger.info("未配置进群自动检测云黑功能的群白名单，跳过检测")
            return
            
        # 检查API Key是否配置
        api_key = self.config.get("api_key", "")
        if not api_key:
            logger.warning("API Key未配置，无法检测新成员云黑状态")
            return
            
        try:
            # 构造API请求URL
            api_url = f"https://fz.qimeng.fun/OpenAPI/all_f.php?id={user_id}&key={api_key}"
            
            logger.info(f"正在查询成员 {user_id} 的云黑状态，请求URL: {api_url}")
            
            # 发起API请求
            data = await self._rate_limited_request(api_url)
            
            # 解析返回数据
            if data.get("info"):
                info_list = data.get("info", [])
                if len(info_list) >= 3:
                    yunhei_info = info_list[2]  # 云黑记录信息
                    
                    # 辅助函数用于判断布尔值
                    def is_true(value):
                        return str(value).lower() == 'true' if value is not None else False
                        
                    # 构建API返回信息
                    reason = yunhei_info.get('note', '无说明')
                    type_ = yunhei_info.get('type', '未知')
                    admin = yunhei_info.get('admin', '未知')
                    level = yunhei_info.get('level', '无')
                    date = yunhei_info.get('date', '无记录')
                    
                    # 如果是空字符串，则设置为"无"或友好的提示信息
                    if not reason or reason.strip() == "":
                        reason = "无说明"
                    if not type_ or type_.strip() == "":
                        type_ = "未知"
                    if not admin or admin.strip() == "":
                        admin = "未知"
                    if not level or level.strip() == "":
                        level = "无"
                    if not date or date.strip() == "":
                        date = "无记录"
                    
                    # 检查是否为云黑成员
                    if is_true(yunhei_info.get('yh')):
                        logger.info(f"检测到云黑成员: {user_id}，原因: {reason}，类型: {type_}，日期: {date}")
                        
                        # 踢出成员
                        await event.bot.set_group_kick(
                            group_id=group_id_int, 
                            user_id=int(user_id), 
                            reject_add_request=False
                        )
                        
                        # 发送踢出通知消息
                        kick_message = f"检测到云黑成员 {user_id} 已被自动踢出\n原因: {reason}\n类型: {type_}\n日期: {date}"
                        yield event.plain_result(kick_message)
                        
                        logger.info(f"已踢出云黑成员: {user_id}，原因: {reason}，类型: {type_}\n日期: {date}")
                    else:
                        logger.info(f"成员 {user_id} 不是云黑用户，原因: {reason}，类型: {type_}，等级: {level}，日期: {date}")
                        
                        # 发送正常成员检测信息
                        normal_message = f"新成员 {user_id} 不是云黑用户\n原因: {reason}\n类型: {type_}\n等级: {level}\n日期: {date}"
                        yield event.plain_result(normal_message)
            else:
                logger.info(f"查询成员 {user_id} 的云黑状态返回空数据")
                        
        except Exception as e:
            logger.error(f"检测新成员 {user_id} 云黑状态时出错: {str(e)}")

    @filter.command("大扫除", "扫描所有群云黑成员，大扫除!")
    async def scan_group_members(self, event: AstrMessageEvent):
        # 检查是否在群聊中使用该命令
        if not event.get_group_id():
            yield event.plain_result("该命令只能在群聊中使用")
            return
            
        # 检查API Key是否配置
        api_key = self.config.get("api_key", "")
        if not api_key:
            yield event.plain_result("请先在插件配置中填写申请的API Key")
            return

        yield event.plain_result("获取中...")
        
        try:
            # 获取群成员列表
            client = event.bot
            group_id = event.get_group_id()
            members_data = await client.get_group_member_list(group_id=int(group_id))
            # 提取成员QQ号列表
            group_members = [str(member['user_id']) for member in members_data]
        except Exception as e:
            logger.error(f"获取群成员列表时出错: {str(e)}")
            yield event.plain_result("获取群成员列表失败")
            return
        
        if not group_members:
            yield event.plain_result("无法获取群成员列表")
            return
            
        # 批量检查所有群成员
        blacklisted_members = await self._batch_check_users(group_members, api_key)
        
        if not blacklisted_members:
            yield event.plain_result("扫描完成！未发现云黑成员。")
            return
            
        # 保存待踢出成员列表
        group_id = event.get_group_id()
        self.pending_kick_members[group_id] = blacklisted_members
        
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
    async def confirm_kick_members(self, event: AstrMessageEvent):
        # 检查是否在群聊中使用该命令
        if not event.get_group_id():
            yield event.plain_result("该命令只能在群聊中使用")
            return
            
        group_id = event.get_group_id()
        
        # 检查是否有待踢出的成员
        if group_id not in self.pending_kick_members or not self.pending_kick_members[group_id]:
            yield event.plain_result("当前没有待踢出的云黑成员。请先执行「扫描群成员」命令。")
            return
            
        blacklisted_members = self.pending_kick_members[group_id]
        kicked_count = 0
        
        # 踢出所有云黑成员
        for member in blacklisted_members:
            member_id = member['id']
            try:
                # 使用set_group_kick接口踢出成员
                await self.context.bot.set_group_kick(group_id=group_id, user_id=member_id, reject_add_request=False)
                kicked_count += 1
                logger.info(f"已踢出云黑成员: {member_id}")
            except Exception as e:
                logger.error(f"踢出成员 {member_id} 时出错: {str(e)}")
                continue
                
        # 清除已处理的待踢出成员列表
        del self.pending_kick_members[group_id]
        
        result = f"已完成踢出操作！\n成功踢出云黑成员数：{kicked_count}\n失败数：{len(blacklisted_members) - kicked_count}"
        yield event.plain_result(result)