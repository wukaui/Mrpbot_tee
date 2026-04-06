#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Mrpbot 2.0

主入口文件
"""

import asyncio
import sys
import signal
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils import setup_logger, load_config
from src.core import Mrpbot


async def main():
    """主函数"""
    
    # 设置日志
    logger = setup_logger('Mrpbot')
    logger.info("=" * 60)
    logger.info("Mrpbot 2.0")
    logger.info("=" * 60)
    
    # 加载配置
    logger.info("正在加载配置...")
    config = load_config('config/bot.yaml')
    
    if not config:
        logger.error("配置加载失败，请检查配置文件")
        return 1

    # 按配置应用日志级别（默认 INFO）
    level_name = str(config.get('bot', {}).get('log_level', 'INFO')).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.getLogger().setLevel(level)
    logger.setLevel(level)
    
    logger.info("✓ 配置已加载")
    
    # 创建机器人
    logger.info("正在创建机器人...")
    bot = Mrpbot(config)
    
    # 信号处理
    # Windows 不支持 asyncio 信号处理，需要跳过
    import platform
    if platform.system() != 'Windows':
        loop = asyncio.get_event_loop()
        
        def signal_handler():
            logger.info("收到停止信号...")
            asyncio.create_task(bot.stop())
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
        logger.info("✓ 信号处理已设置（非 Windows）")
    else:
        logger.info("⚠️ Windows 系统，跳过信号处理（使用 KeyboardInterrupt）")
    
    # 启动机器人
    try:
        await bot.start()
        
        # 保持运行
        logger.info("机器人运行中... (Ctrl+C 停止)")
        while bot.is_running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"运行错误：{e}", exc_info=True)
        return 1
    finally:
        await bot.stop()
        logger.info("✓ Mrpbot 2.0 已停止")
    
    return 0


if __name__ == '__main__':
    # 检查 Python 版本
    if sys.version_info < (3, 8):
        print("错误：需要 Python 3.8 或更高版本")
        sys.exit(1)
    
    # 运行
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
