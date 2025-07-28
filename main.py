from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import httpx

@register("asbot_plugin_furry-API-hy", "furryhm", "调用趣绮梦云黑API的群黑云查询踢出的插件", "1.0.0")
class QimengYunheiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 存储待踢出的云黑成员列表
        self.pending_kick_members = {}

    @filter.command("扫描云黑成员", "扫描所有群云黑成员，显示云黑成员列表")
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
            
        blacklisted_members = []
        
        for member_id in group_members:
            # 构造API请求URL
            api_url = f"https://fz.qimeng.fun/OpenAPI/all_f.php?id={member_id}&key={api_key}"
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(api_url, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    
                # 解析返回数据
                if data.get("info"):
                    info_list = data.get("info", [{}])[0].get("info", [])
                    if len(info_list) >= 3:
                        yunhei_info = info_list[2]  # 云黑记录信息
                        
                        # 辅助函数用于判断布尔值
                        def is_true(value):
                            return str(value).lower() == 'true' if value is not None else False
                            
                        # 检查是否为云黑成员
                        if is_true(yunhei_info.get('yh')):
                            # 保存云黑成员信息
                            blacklisted_members.append({
                                'id': member_id,
                                'reason': yunhei_info.get('note', '无说明'),
                                'type': yunhei_info.get('type', '未知'),
                                'admin': yunhei_info.get('admin', '未知'),
                                'level': yunhei_info.get('level', '无'),
                                'date': yunhei_info.get('date', '无记录')
                            })
                
            except Exception as e:
                logger.error(f"查询成员 {member_id} 时出错: {str(e)}")
                continue
                
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