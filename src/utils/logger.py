# Logger Setup
"""
日志配置
"""

import logging
import os
from datetime import datetime


def setup_logger(name: str = 'Mrpbot', level: int = logging.INFO) -> logging.Logger:
    """
    设置日志
    
    Args:
        name: 日志名称
        level: 日志级别
        
    Returns:
        Logger 实例
    """
    
    # 确保日志目录存在
    os.makedirs('logs', exist_ok=True)
    
    # 日志文件（按日期分割）
    log_file = os.path.join('logs', f"{name}_{datetime.now().strftime('%Y%m%d')}.log")
    
    # 配置
    logging.basicConfig(
        level=level,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ]
    )
    
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 第三方网络日志默认降噪，避免每次请求都刷屏
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    
    return logger
