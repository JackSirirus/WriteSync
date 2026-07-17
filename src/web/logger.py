"""
WriteSync 日志模块

记录：HTTP 请求 / 会话生命周期 / LLM 调用 / 图执行 / 面板操作

使用：在 app.py 中调用 init_logging() 初始化

日志级别指南：
- DEBUG: 所有细节（state 值、路由判断依据、执行耗时）
- INFO: 正常流程事件（节点进入、interrupt 触发、用户操作）
- WARNING: 非关键异常（LLM 超时降级、重试、非关键路径失败）
- ERROR: 关键失败（LLM 不可用、SQL 错误、未捕获异常）
"""

import logging
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime

# 日志器
logger = logging.getLogger("writesync")
logger.setLevel(logging.DEBUG)

# 控制台输出（简洁格式）
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

# 文件输出（详细格式，记录到 logs/ 目录）
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
_log_filename = LOG_DIR / f"writesync-{datetime.now().strftime('%Y%m%d')}.log"
file_handler = logging.FileHandler(_log_filename, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))

logger.addHandler(console)
logger.addHandler(file_handler)


def init_logging():
    """初始化日志（在应用启动时调用）"""
    logger.info("=" * 50)
    logger.info("WriteSync 服务启动")
    logger.info(f"日志文件: {LOG_DIR}")
    logger.info("=" * 50)


def log_request(method: str, path: str, status: int, duration_ms: float):
    """记录 HTTP 请求"""
    status_icon = "✓" if status < 400 else "✗"
    logger.debug(f"REQ {method} {path} → {status} ({duration_ms:.0f}ms)")
    if status >= 500:
        logger.error(f"REQ {method} {path} → {status} ({duration_ms:.0f}ms)")
    elif status >= 400:
        logger.warning(f"REQ {method} {path} → {status} ({duration_ms:.0f}ms)")


def log_session_create(session_id: str, platform: str, model: str, mode: str):
    logger.info(f"SESSION [{session_id[:8]}] 创建 | 平台={platform} | 模型={model} | 模式={mode}")


def log_session_resume(session_id: str, action: str):
    logger.info(f"SESSION [{session_id[:8]}] 恢复 | action={action}")


def log_session_done(session_id: str):
    logger.info(f"SESSION [{session_id[:8]}] 完成")


def log_session_error(session_id: str, error: str):
    logger.error(f"SESSION [{session_id[:8]}] 错误: {error[:200]}")


def log_interrupt(session_id: str, interrupt_text: str):
    logger.info(f"SESSION [{session_id[:8]}] 中断: {interrupt_text[:100]}")


def log_llm_call(model: str, purpose: str, duration_s: float, success: bool):
    status = "OK" if success else "FAIL"
    level = logging.INFO if success else logging.ERROR
    logger.log(level, f"LLM [{model}] {purpose} → {status} ({duration_s:.1f}s)")


def log_panel_save(session_id: str, panel: str, keys: list):
    logger.debug(f"PANEL [{session_id[:8]}] 保存 {panel}: {keys}")


def log_export(session_id: str, fmt: str):
    """记录导出操作"""
    logger.info(f"EXPORT [{session_id[:8]}] 导出格式={fmt}")


# ── Graph 图日志 ──

def log_graph_node(session_id: str, node_name: str, action: str = ""):
    """记录图节点进入"""
    msg = f"GRAPH [{session_id[:8] if session_id else '?'}] 进入节点: {node_name}"
    if action:
        msg += f" | action={action}"
    logger.info(msg)


def log_graph_route(session_id: str, node_name: str, route: str):
    """记录图路由决策"""
    logger.info(f"ROUTE [{session_id[:8] if session_id else '?'}] {node_name} → {route}")


def log_resume_detail(session_id: str, action: str, feedback: str, resume_value: dict):
    """记录 resume 的详细信息（用于调试中断循环）"""
    logger.info(
        f"RESUME [{session_id[:8]}] action={action} feedback={feedback[:50] if feedback else ''} "
        f"value={resume_value}"
    )


def log_interrupt_detail(session_id: str, node: str, interrupt_text: str, state_flags: str = ""):
    """记录中断的详细信息，包含当前状态标记"""
    logger.info(
        f"INTERRUPT [{session_id[:8]}] node={node} text={interrupt_text[:80]} "
        f"flags={state_flags}"
    )


def log_user_action(session_id: str, action: str, detail: str = ""):
    """记录用户操作"""
    logger.info(f"USER [{session_id[:8]}] action={action} detail={detail[:200]}")


def log_state_flags(session_id: str, node: str, flags: dict):
    """记录节点执行前的关键状态标记，帮助追踪流程状态"""
    parts = [f"{k}={v}" for k, v in sorted(flags.items()) if v is not None]
    logger.debug(f"STATE [{session_id[:8]}] {node} | {' | '.join(parts)}")


def log_route_decision(session_id: str, node: str, route: str, reason: str = ""):
    """记录路由决策及其依据"""
    msg = f"ROUTE [{session_id[:8]}] {node} → {route}"
    if reason:
        msg += f"  reason={reason}"
    logger.info(msg)


def log_graph_error(session_id: str, node: str, error: Exception):
    """记录图执行错误，含完整堆栈"""
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    logger.error(f"GRAPH_ERROR [{session_id[:8] if session_id else '?'}] {node}: {error}\n{tb}")


def log_agent_exec(session_id: str, agent_name: str, action: str = "start", detail: str = ""):
    """记录 Agent 执行开始/结束"""
    msg = f"AGENT [{session_id[:8] if session_id else '?'}] {agent_name} [{action}]"
    if detail:
        msg += f" {detail}"
    if action == "start":
        logger.info(msg)
    else:
        logger.debug(msg)
