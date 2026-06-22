# 导入logging标准日志库核心模块
import logging
import os
# 导入按时间自动切割日志文件的处理器（避免单个日志文件无限膨胀）
from logging.handlers import TimedRotatingFileHandler
# 确保日志目录存在
os.makedirs("logs", exist_ok=True)


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    Windows 安全版按时间轮转日志处理器。

    标准 TimedRotatingFileHandler 在 Windows 上轮转时会调用 os.rename()，
    如果旧日志文件被其他进程（如编辑器、调试器）占用，会抛出
    PermissionError: [WinError 32]，导致日志系统崩溃报错。

    此子类覆盖 rotate() 方法：
    - 先尝试正常重命名
    - 失败时静默跳过，保留当前日志文件继续写入，不抛出异常
    """

    def rotate(self, source, dest):
        """覆盖轮转方法，捕获 Windows 文件占用错误并静默跳过"""
        try:
            super().rotate(source, dest)
        except PermissionError:
            # 文件被占用时跳过本次轮转，继续向当前文件写入
            pass

    def doRollover(self):
        """覆盖 doRollover，同样捕获轮转过程中可能的权限错误"""
        try:
            super().doRollover()
        except PermissionError:
            pass


def get_logger(name=__name__):
    """
    封装获取日志器的工厂函数，全局只生成一份日志配置，避免重复添加处理器
    :param name: 日志器名称，默认传入当前模块名__name__，不同模块可隔离日志器
    :return: 配置好格式、输出渠道、日志级别后的logger对象
    """
    # 1. 获取指定名称的logger实例（logging是单例模式，同名logger只会创建一次）
    logger = logging.getLogger(name)
    # 设置logger全局最低日志级别：DEBUG，所有>=DEBUG级别的日志才会被后续处理器处理
    logger.setLevel(logging.DEBUG)
    # 禁止日志向上传递给根日志器，防止控制台重复打印多条相同日志
    logger.propagate = False
    # 2. 判重：如果当前logger已经绑定过处理器，直接返回，不再重复配置
    # 解决多次导入该函数、重复addHandler造成日志重复输出问题
    if logger.handlers:
        return logger
    # 3. 定义日志输出格式字符串，各个占位符含义后文详解
    fmt_str = "%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)3d | %(message)s"
    # 实例化格式对象，同时指定时间字符串格式化样式
    fmt = logging.Formatter(fmt_str, datefmt="%Y-%m-%d %H:%M:%S")
    # ========== 处理器1：StreamHandler 控制台输出 ==========
    sh = logging.StreamHandler()  # 构建控制台输出处理器，日志打印到终端
    sh.setLevel(logging.INFO)     # 该处理器单独级别：控制台只输出INFO及更高级别日志
    sh.setFormatter(fmt)          # 给控制台处理器绑定上面定义好的日志格式
    # ========== 处理器2：SafeTimedRotatingFileHandler 按天切分日志文件 ==========
    th = SafeTimedRotatingFileHandler(
        "logs/run.log",      # 日志主文件名
        when="D",            # 切割单位：D=天；可选H小时/M分钟/S秒
        interval=1,          # 间隔周期：每1天切割一次新日志文件
        backupCount=15,      # 日志备份保留数量：只留存最近15天的日志，自动删除更早文件
        encoding="utf-8",    # 编码设置utf-8，解决中文日志乱码
        delay=True,          # 延迟到第一次写入时才打开文件，减少文件占用时间窗口
    )
    th.setLevel(logging.DEBUG)    # 文件处理器级别：DEBUG及以上全部写入日志文件
    th.setFormatter(fmt)          # 文件日志也使用同一套格式模板
    # 把两个处理器绑定到logger日志器上
    logger.addHandler(sh)
    logger.addHandler(th)
    # 返回配置完成的日志器实例
    return logger


# 全局实例化一次logger，项目其他py文件可直接导入使用，无需重复初始化
logger = get_logger()