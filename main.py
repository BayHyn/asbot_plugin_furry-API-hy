from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json
import os
import re


@register("asbot_plugin_furry-gg", "furryhm", "公告插件，支持识别广告、发送配置文件广告、公告管理员发送公告等功能", "1.0.0")
class AnnouncementPlugin(Star):
    def __init__(self, context: Context) -> None:
        self.context = context
        # 获取插件文件所在目录
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.plugin_dir, "_conf_schema.json")
        self.config = self.load_config()
        
    def load_config(self):
        """加载配置文件"""
        if not os.path.exists(self.config_path):
            # 默认配置
            default_config = {
                "announcements": [],
                "ad_keywords": ["广告", "推广", "营销", "出售", "购买", "优惠", "折扣"],
                "blacklist": [],
                "announcement_admins": []
            }
            self.save_config(default_config)
            return default_config
        else:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
            
    def save_config(self, config=None):
        """保存配置文件"""
        if config is None:
            config = self.config
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            
    def is_announcement_admin(self, user_id: str) -> bool:
        """检查用户是否为公告管理员"""
        return user_id in self.config.get("announcement_admins", [])
        
    @filter.command("gg_help", "查看公告插件使用帮助")
    async def show_help(self, event: AstrMessageEvent):
        """显示插件使用帮助"""
        help_text = """公告插件使用说明：
        
插件会在首次运行时在插件目录自动生成配置文件 _conf_schema.json

📌 指令列表：

公告管理（管理员）：
/ad_add <内容>  - 添加公告内容
/ad_list        - 查看公告列表
/ad_del <索引>  - 删除指定公告
/ad_send <索引> - 发送配置的公告

公告管理员管理（管理员）：
/admin_add <ID> - 添加公告管理员
/admin_list     - 查看公告管理员列表
/admin_del <ID> - 删除公告管理员

黑名单管理（管理员）：
/blacklist_add <ID> - 添加用户到黑名单
/blacklist_list     - 查看黑名单用户
/blacklist_del <ID> - 从黑名单移除用户

公告发送（公告管理员）：
/announce <内容> - 发送公告给所有群和好友

💡 提示：
1. 首次使用请先设置公告管理员
2. 配置文件会自动保存在插件目录下的 _conf_schema.json
3. 只有公告管理员可以发送公告"""
        
        yield event.plain_result(help_text)
        
    @filter.command("ad_add", "添加公告/广告内容到配置文件")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def add_advertisement(self, event: AstrMessageEvent, *, content: str = ""):
        """添加公告/广告内容到配置文件"""
        if not content:
            yield event.plain_result("请提供要添加的公告内容")
            return
            
        self.config["announcements"].append(content)
        self.save_config()
        yield event.plain_result("公告内容已添加")
        
    @filter.command("ad_list", "列出所有公告/广告内容")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_advertisement(self, event: AstrMessageEvent):
        """列出所有公告/广告内容"""
        announcements = self.config.get("announcements", [])
        if not announcements:
            yield event.plain_result("暂无公告内容")
            return
            
        msg = "公告列表：\n"
        for i, announcement in enumerate(announcements, 1):
            msg += f"{i}. {announcement}\n"
            
        yield event.plain_result(msg)
        
    @filter.command("ad_del", "删除指定索引的公告内容")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def delete_advertisement(self, event: AstrMessageEvent, index: int = None):
        """删除指定索引的公告内容"""
        if index is None:
            yield event.plain_result("请提供要删除的公告索引")
            return
            
        announcements = self.config.get("announcements", [])
        if index < 1 or index > len(announcements):
            yield event.plain_result("索引超出范围")
            return
            
        del announcements[index-1]
        self.save_config()
        yield event.plain_result("公告内容已删除")
        
    @filter.command("ad_send", "发送配置文件中的公告")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def send_advertisement(self, event: AstrMessageEvent, index: int = None):
        """发送配置文件中的公告"""
        if index is None:
            yield event.plain_result("请提供要发送的公告索引")
            return
            
        announcements = self.config.get("announcements", [])
        if index < 1 or index > len(announcements):
            yield event.plain_result("索引超出范围")
            return
            
        announcement = announcements[index-1]
        # 这里需要根据实际框架API实现广播功能
        # 由于没有找到相关API，暂时只返回公告内容
        yield event.plain_result(f"将发送公告: {announcement}")
        
    @filter.command("admin_add", "添加公告管理员")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def add_announcement_admin(self, event: AstrMessageEvent, user_id: str = None):
        """添加公告管理员"""
        if not user_id:
            yield event.plain_result("请提供用户ID")
            return
            
        if user_id not in self.config["announcement_admins"]:
            self.config["announcement_admins"].append(user_id)
            self.save_config()
            yield event.plain_result(f"用户 {user_id} 已添加为公告管理员")
        else:
            yield event.plain_result(f"用户 {user_id} 已经是公告管理员")
            
    @filter.command("admin_list", "列出所有公告管理员")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_announcement_admin(self, event: AstrMessageEvent):
        """列出所有公告管理员"""
        announcement_admins = self.config.get("announcement_admins", [])
        if not announcement_admins:
            yield event.plain_result("暂无公告管理员")
            return
            
        msg = "公告管理员列表：\n"
        for admin in announcement_admins:
            msg += f"- {admin}\n"
            
        yield event.plain_result(msg)
        
    @filter.command("admin_del", "删除公告管理员")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def delete_announcement_admin(self, event: AstrMessageEvent, user_id: str = None):
        """删除公告管理员"""
        if not user_id:
            yield event.plain_result("请提供用户ID")
            return
            
        if user_id in self.config["announcement_admins"]:
            self.config["announcement_admins"].remove(user_id)
            self.save_config()
            yield event.plain_result(f"用户 {user_id} 已从公告管理员中移除")
        else:
            yield event.plain_result(f"用户 {user_id} 不是公告管理员")
            
    @filter.command("blacklist_add", "添加用户到黑名单")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def add_to_blacklist(self, event: AstrMessageEvent, user_id: str = None):
        """添加用户到黑名单"""
        if not user_id:
            yield event.plain_result("请提供用户ID")
            return
            
        if user_id not in self.config["blacklist"]:
            self.config["blacklist"].append(user_id)
            self.save_config()
            yield event.plain_result(f"用户 {user_id} 已添加到黑名单")
        else:
            yield event.plain_result(f"用户 {user_id} 已经在黑名单中")
            
    @filter.command("blacklist_list", "列出所有黑名单用户")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_blacklist(self, event: AstrMessageEvent):
        """列出所有黑名单用户"""
        blacklist = self.config.get("blacklist", [])
        if not blacklist:
            yield event.plain_result("黑名单为空")
            return
            
        msg = "黑名单用户列表：\n"
        for user in blacklist:
            msg += f"- {user}\n"
            
        yield event.plain_result(msg)
        
    @filter.command("blacklist_del", "从黑名单移除用户")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def remove_from_blacklist(self, event: AstrMessageEvent, user_id: str = None):
        """从黑名单移除用户"""
        if not user_id:
            yield event.plain_result("请提供用户ID")
            return
            
        if user_id in self.config["blacklist"]:
            self.config["blacklist"].remove(user_id)
            self.save_config()
            yield event.plain_result(f"用户 {user_id} 已从黑名单中移除")
        else:
            yield event.plain_result(f"用户 {user_id} 不在黑名单中")
            
    @filter.command("announce", "发送公告（仅公告管理员）")
    async def send_announcement(self, event: AstrMessageEvent, *, content: str = ""):
        """发送公告（仅公告管理员）"""
        user_id = str(event.get_sender_id())
        
        if not self.is_announcement_admin(user_id):
            yield event.plain_result("权限不足，仅公告管理员可发送公告")
            return
            
        if not content:
            yield event.plain_result("请提供公告内容")
            return
            
        # 这里需要根据实际框架API实现广播功能
        # 由于没有找到相关API，暂时只返回公告内容
        yield event.plain_result(f"将发送公告: {content}")