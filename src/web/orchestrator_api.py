"""
SSE 事件流处理器 — 将 OrchestratorSession 接入 FastAPI

提供：
- SSE 流式端点
- 用户响应投递机制
- 断线恢复支持
"""

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from src.orchestrator.loop import OrchestratorSession
from src.orchestrator.workspace import Workspace, load_workspace
from src.orchestrator.models import SSEEventType

logger = logging.getLogger("writesync")

# 活跃的 orchestrator 会话 {project_id: OrchestratorSession}
_orchestrator_sessions: dict[str, OrchestratorSession] = {}
# SSE 连接队列 {project_id: asyncio.Queue}
_sse_queues: dict[str, asyncio.Queue] = {}


def get_or_create_session(workspace: Workspace) -> OrchestratorSession:
    """获取或创建 OrchestratorSession"""
    pid = workspace.project_id
    if pid in _orchestrator_sessions:
        session = _orchestrator_sessions[pid]
        if session.is_running():
            return session

    session = OrchestratorSession(workspace)
    _orchestrator_sessions[pid] = session
    return session


def remove_session(project_id: str):
    """清理会话"""
    _orchestrator_sessions.pop(project_id, None)
    _sse_queues.pop(project_id, None)


def send_to_session(project_id: str, approved: bool, feedback: str = "",
                    scope: str = "all", edited_content=None,
                    selected_action: str = "") -> bool:
    """向运行中的会话发送用户响应

    v0.5.0 Suggestion Mode: selected_action 用于选择备选方案中的某一项
    （用户从 suggestion SSE 事件的 options 中挑选）。空字符串表示使用主建议。
    """
    session = _orchestrator_sessions.get(project_id)
    if session is None:
        return False
    if not session.is_running():
        return False
    session.user_respond(approved=approved, feedback=feedback, scope=scope,
                         edited_content=edited_content,
                         selected_action=selected_action)
    return True


async def sse_event_stream(request: Request, workspace: Workspace):
    """
    SSE 事件流 — 由 FastAPI StreamingResponse 使用
    
    将 OrchestratorSession.run() 的 SSEEvent yield 转换为
    Server-Sent Events 格式发送给前端。
    
    v0.4.0 修复: 使用后台任务 + 队列架构，在长时间 LLM 调用期间
    通过 SSE heartbeat 保持连接存活（防止 uvicorn/代理超时断开）。
    """
    session = get_or_create_session(workspace)
    pid = workspace.project_id

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        _sse_queues[pid] = queue

        orchestrator_error = None

        async def run_orchestrator():
            """后台任务：运行编排器，将事件推入队列"""
            nonlocal orchestrator_error
            try:
                async for event in session.run():
                    await queue.put(event)
                await queue.put(None)  # 完成信号
            except Exception as e:
                logger.exception("编排器后台任务异常: %s", pid)
                orchestrator_error = e
                await queue.put(None)
                # 推送错误事件到队列，确保前端收到
                error_event = type('SSEEvent', (), {
                    'type': 'error',
                    'data': {'message': str(e)},
                })()
                await queue.put(error_event)

        task = asyncio.create_task(run_orchestrator())

        try:
            while True:
                try:
                    # 等待下一个事件，3s 无数据则发送心跳
                    # 必须 < uvicorn 默认 --timeout-keep-alive=5s，否则连接被静默断开
                    event = await asyncio.wait_for(queue.get(), timeout=3.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        logger.info("SSE 客户端断开 (heartbeat): %s", pid)
                        break
                    # SSE 心跳 — 注释行被客户端忽略，但保持 HTTP 连接存活
                    yield ": heartbeat\n\n"
                    continue

                if event is None:
                    # 编排器完成
                    if orchestrator_error:
                        logger.error("编排器异常终止: %s", orchestrator_error)
                        error_data = json.dumps(
                            {"message": str(orchestrator_error)},
                            ensure_ascii=False,
                        )
                        yield f"event: error\ndata: {error_data}\n\n"
                    break

                # 格式化 SSE 事件
                sse_data = json.dumps(event.data, ensure_ascii=False, default=str)
                sse_line = f"event: {event.type}\ndata: {sse_data}\n\n"
                yield sse_line

                if await request.is_disconnected():
                    logger.info("SSE 客户端断开: %s", pid)
                    task.cancel()
                    break
        except asyncio.CancelledError:
            pass
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            _sse_queues.pop(pid, None)
            # 不销毁会话：允许 EventSource 自动重连时复用同一编排器会话

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
