from plugin_base import PluginBase
from datetime import datetime

class DatetimePlugin(PluginBase):
    name = "datetime"
    version = "1.0"

    def on_llm_context(self, user_input: str) -> str:
        now = datetime.now()
        weekday = ["一","二","三","四","五","六","日"][now.weekday()]
        return f"当前时间：{now.strftime('%Y年%m月%d日 %H:%M')}，星期{weekday}"
