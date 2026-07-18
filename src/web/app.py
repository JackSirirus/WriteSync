"""
WriteSync Web UI — FastAPI 应用 (v0.3.0)
 
运行：uvicorn src.web.app:app --reload
访问：http://localhost:8000
"""

import os, sys, json, time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import asdict

# 自动加载项目根目录的 .env 文件
from dotenv import load_dotenv
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / ".env")

from fastapi import FastAPI, Request, Form, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

import warnings
warnings.filterwarnings("ignore", message=".*Deserializing unregistered.*")
warnings.filterwarnings("ignore", message=".*Pydantic V1.*")

from src.state.persistence import PersistenceManager
from src.state.state_types import WriteSyncState
from src.orchestrator.workspace import Workspace, load_workspace, init_workspace
from src.web.orchestrator_api import sse_event_stream, send_to_session
from src.utils.provider_config import AIProviderConfig
from src.utils.provider_manager import get_provider_manager

from .logger import (
    init_logging, log_request, log_panel_save, log_export, logger,
)

app = FastAPI(title="WriteSync")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# v0.5.0: 前端模块化 JS 文件的静态挂载
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "templates")), name="static")
init_logging()

_pm = PersistenceManager(projects_dir="projects")
_v2_ws: dict[str, Workspace] = {}


def _get_ws(project_id: str) -> Optional[Workspace]:
    if project_id in _v2_ws:
        return _v2_ws[project_id]
    ws = load_workspace(project_id)
    if ws:
        _v2_ws[project_id] = ws
    return ws


@app.middleware("http")
async def log_mw(request: Request, call_next):
    t0 = time.time()
    resp = await call_next(request)
    log_request(request.method, request.url.path, resp.status_code, (time.time() - t0) * 1000)
    return resp


# =============================================================================
# Pages
# =============================================================================

@app.get("/", response_class=HTMLResponse)
@app.get("/workbench", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "workbench.html")


# =============================================================================
# Projects
# =============================================================================

@app.get("/api/projects")
def list_projects():
    return JSONResponse(_pm.list_projects())


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    _v2_ws.pop(project_id, None)
    ok = _pm.delete_project(project_id)
    return JSONResponse({"ok": ok})


# =============================================================================
# Legacy compat endpoints (frontend still uses old API paths)
# =============================================================================

@app.post("/api/new")
async def start_legacy(idea: str = Form(""), platform: str = Form("起点"),
                       model: str = Form(""), full: bool = Form(False)):
    ws = Workspace.create(
        name=idea[:40].strip() if idea else "新项目",
        platform=platform,
        seed_idea=idea,
    )
    ws.save()
    ws.build_context_cache()
    _v2_ws[ws.project_id] = ws
    return JSONResponse({
        "session_id": ws.project_id,
        "project_name": ws.project_name,
        "project_id": ws.project_id,
        "dashboard": asdict(ws.get_dashboard()),
        "done": False,
    })


@app.post("/api/load/{project_id}")
def load_project(project_id: str):
    ws = load_workspace(project_id)
    if ws is None:
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    _v2_ws[project_id] = ws
    s = ws.raw_state
    state_dict = {}
    if s.story:
        state_dict["story"] = {
            "one_sentence": s.story.step1.one_sentence,
            "tag": s.story.step1.tag,
            "confirmed": s.story.confirmed_at is not None,
        }
    if s.characters and s.characters.characters:
        state_dict["characters"] = {
            "list": [{"name": c.name, "role": c.role, "personality": c.personality,
                       "goal": c.goal, "arc": c.arc or ""} for c in s.characters.characters],
            "confirmed": s.characters.confirmed_at is not None,
        }
    if s.world:
        state_dict["world"] = {
            "system": s.world.power_system.system_name if s.world.power_system else "",
            "confirmed": s.world.confirmed_at is not None,
        }
    if s.chapter_outline:
        state_dict["outline"] = {
            "total": s.chapter_outline.total_chapters,
            "written": [ch.chapter_number for ch in s.chapter_outline.chapters],
            "confirmed": s.chapter_outline.confirmed_at is not None,
        }
    if s.drafts and s.drafts.chapters:
        drafts = {}
        for n, cd in s.drafts.chapters.items():
            content = ""
            if cd.final:
                content = cd.final.content
            elif cd.draft:
                content = cd.draft.content
            drafts[str(n)] = {"content": content, "stage": cd.stage, "word_count": cd.word_count}
        state_dict["drafts"] = drafts
    return JSONResponse({
        "session_id": project_id,
        "state": state_dict,
        "done": False,
    })


@app.post("/api/resume/{project_id}")
async def resume_legacy(project_id: str, action: str = Form("y"),
                        feedback: str = Form("")):
    approved = action.lower() in ("true", "1", "yes", "y", "confirm", "edit", "select_topic")
    ok = send_to_session(project_id, approved=approved,
                         feedback=feedback)
    return JSONResponse({"ok": ok})


@app.get("/api/status/{project_id}")
def status_legacy(project_id: str):
    """Legacy status endpoint: returns state in old format frontend expects"""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"state": {}, "interrupt": [], "done": False, "error": "项目不存在"}, status_code=404)
    s = ws.raw_state
    state = {}
    if s.story:
        state["story"] = {
            "one_sentence": s.story.step1.one_sentence,
            "tag": s.story.step1.tag,
            "confirmed": s.story.confirmed_at is not None,
        }
    if s.characters and s.characters.characters:
        state["characters"] = {
            "list": [{"name": c.name, "role": c.role, "personality": c.personality,
                       "goal": c.goal, "arc": c.arc or ""} for c in s.characters.characters],
            "confirmed": s.characters.confirmed_at is not None,
        }
    if s.world:
        state["world"] = {
            "system": s.world.power_system.system_name if s.world.power_system else "",
            "confirmed": s.world.confirmed_at is not None,
        }
    if s.chapter_outline:
        state["outline"] = {
            "total": s.chapter_outline.total_chapters,
            "written": [ch.chapter_number for ch in s.chapter_outline.chapters],
            "confirmed": s.chapter_outline.confirmed_at is not None,
        }
    return JSONResponse({"state": state, "interrupt": [], "done": False, "error": None})


@app.get("/api/export/{project_id}")
def export_legacy(project_id: str, fmt: str = "md"):
    return export_project(project_id, fmt)


# =============================================================================
# V2 Orchestrator API
# =============================================================================

@app.post("/api/v2/start")
async def start_v2(idea: str = Form(""), platform: str = Form("起点"),
                    project_id: str = Form("")):
    ws = None
    if project_id:
        ws = _get_ws(project_id)
    if ws is None:
        name = idea[:40].strip() if idea else "新项目"
        ws = Workspace.create(name, platform, idea)
        if idea:
            ws.set_seed_idea(idea)
        ws.save()
    ws.build_context_cache()
    _v2_ws[ws.project_id] = ws
    return JSONResponse({
        "ok": True, "project_id": ws.project_id,
        "project_name": ws.project_name,
        "stream_url": f"/api/v2/stream/{ws.project_id}",
        "dashboard": asdict(ws.get_dashboard()),
    })


@app.get("/api/v2/stream/{project_id}")
async def stream_v2(request: Request, project_id: str):
    ws = _get_ws(project_id)
    if ws is None:
        raise HTTPException(404, "项目不存在")
    return await sse_event_stream(request, ws)


@app.post("/api/v2/respond/{project_id}")
async def respond_v2(project_id: str, approved: str = Form("true"),
                      feedback: str = Form(""), scope: str = Form("all"),
                      edited_content: str = Form(""),
                      selected_action: str = Form("")):
    edits = None
    if edited_content:
        try:
            edits = json.loads(edited_content)
        except json.JSONDecodeError:
            pass
    ok = send_to_session(
        project_id,
        approved=(approved.lower() in ("true", "1", "yes", "y")),
        feedback=feedback,
        scope=scope,
        edited_content=edits,
        selected_action=selected_action,
    )
    return JSONResponse({"ok": ok})


@app.post("/api/v2/finish/{project_id}")
async def finish_v2(project_id: str, confirmed: str = Form("true"),
                     feedback: str = Form("")):
    ok = send_to_session(project_id, approved=(confirmed.lower() in ("true", "1", "yes", "y")),
                         feedback=feedback)
    return JSONResponse({"ok": ok})


@app.post("/api/v2/manual-action/{project_id}")
async def manual_action_v2(project_id: str, agent: str = Form(""),
                            instruction: str = Form("")):
    """v0.5.0 Orchestrator Suggestion Mode — 手动模式

    允许用户绕过编排器的决策周期，直接触发任意子 Agent。
    适用于：
    - 用户从 suggestion 事件中拒绝了所有建议，希望手动指定
    - 用户想跳过某个阶段直接进入下一阶段
    - 用户想重做某个阶段（如重新生成角色卡）

    Parameters:
        agent: 子 Agent 名称（story/character/world/outline/writer/proofreader/novel_review）
        instruction: 可选的自定义指令（默认使用通用指令）
    """
    import asyncio
    from src.orchestrator.adapters import call_agent

    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    valid_agents = {"story", "character", "world", "outline", "writer", "proofreader", "novel_review"}
    agent_norm = agent.strip().lower()
    if agent_norm not in valid_agents:
        return JSONResponse({
            "ok": False,
            "error": f"无效 agent: {agent}（可选: {', '.join(sorted(valid_agents))}）"
        }, status_code=400)

    # 提取章节号（仅对 writer/proofreader 有意义）
    chapter_num = 0
    if agent_norm in ("writer", "proofreader") and instruction:
        import re
        m = re.search(r'第\s*(\d+)\s*章', instruction)
        if m:
            chapter_num = int(m.group(1))

    # 直接调用子 Agent（同步 call_agent 放入 to_thread 避免阻塞事件循环）
    try:
        result = await asyncio.to_thread(
            call_agent,
            workspace=ws,
            agent_name=agent_norm,
            instruction=instruction or f"用户手动触发 {agent_norm}",
            chapter_num=chapter_num,
        )
    except Exception as e:
        logger.exception("manual-action 调用失败: project=%s agent=%s", project_id, agent_norm)
        return JSONResponse({
            "ok": False,
            "error": f"Agent 调用失败: {e}",
            "agent": agent_norm,
        }, status_code=500)

    # 刷新上下文缓存 + 持久化
    try:
        ws.build_context_cache()
        ws.save()
    except Exception as e:
        logger.warning("manual-action 状态保存失败: %s", e)

    if result.error:
        return JSONResponse({
            "ok": False,
            "error": result.error,
            "agent": result.agent,
        })

    return JSONResponse({
        "ok": True,
        "agent": result.agent,
        "content": result.content,
        "summary": result.summary,
        "requires_confirmation": result.requires_confirmation,
        "manual": True,
    })


@app.get("/api/v2/status/{project_id}")
async def status_v2(project_id: str):
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    s = ws.raw_state
    status = {
        "ok": True, "project_id": project_id, "project_name": ws.project_name,
        "dashboard": asdict(ws.get_dashboard()),
        "schema_version": ws.schema_version,
        "has_story": ws.has_story(), "has_characters": ws.has_characters(),
        "has_world": ws.has_world(), "has_outline": ws.has_outline(),
        "has_drafts": ws.has_drafts(),
        "total_chapters": ws.get_total_chapters(),
        "written_chapters": ws.get_written_chapters(),
    }
    if s.story:
        five = []
        if s.story.step2:
            five = [s.story.step2.setup, s.story.step2.inciting, s.story.step2.rising,
                    s.story.step2.climax_prep, s.story.step2.resolution]
        status["story"] = {
            "one_sentence": s.story.step1.one_sentence,
            "tag": s.story.step1.tag,
            "five_sentences": five,
            "confirmed": bool(s.story.confirmed_at),
            "confirmed_at": s.story.confirmed_at,
        }
    if s.characters and s.characters.characters:
        status["characters"] = {
            "list": [{"name": c.name, "role": c.role, "personality": c.personality,
                      "goal": c.goal, "arc": (f"{c.arc.start_state}→{c.arc.end_state}" if c.arc else ""),
                      "description": c.description}
                     for c in s.characters.characters],
            "confirmed": bool(s.characters.confirmed_at),
        }
    if s.world:
        ps = s.world.power_system
        status["world"] = {
            "system": ps.system_name if ps else "",
            "tiers": ps.tiers if ps else [],
            "cultivation_rules": ps.cultivation_rules if ps else "",
            "confirmed": bool(s.world.confirmed_at),
        }
    if s.chapter_outline:
        status["outline"] = {
            "total": s.chapter_outline.total_chapters,
            "chapters": [{"number": ch.chapter_number, "title": ch.chapter_title,
                          "core_event": ch.core_event}
                         for ch in s.chapter_outline.chapters],
            "written": [int(n) for n in s.chapter_outline.written_chapters],
            "confirmed": bool(s.chapter_outline.confirmed_at),
        }
    if s.drafts and s.drafts.chapters:
        status["drafts"] = {str(n): {"word_count": cd.word_count, "stage": cd.stage}
                            for n, cd in s.drafts.chapters.items()}
    if s.novel_review:
        status["novel_review"] = {"passed": s.novel_review.passed}

    # Phase 3: Dynamic context including facts + continuity envelope
    if s.dynamic_context:
        ctx = s.dynamic_context
        status["context"] = {
            "character_snapshot": ctx.character_snapshot,
            "recent_chapters_summary": ctx.recent_chapters_summary,
            "unresolved_foreshadows": ctx.unresolved_foreshadows,
            "resolved_foreshadows": ctx.resolved_foreshadows,
            "world_changes": ctx.world_changes,
            "world_consistency_notes": ctx.world_consistency_notes,
            "pacing_state": ctx.pacing_state,
            "plot_progress": ctx.plot_progress,
            "story_beats_remaining": ctx.story_beats_remaining,
            "chapter_word_counts": ctx.chapter_word_counts,
            "updated_at": ctx.updated_at,
            "updated_chapter": ctx.updated_chapter,
            "facts": ctx.facts,
            "continuity_envelope": ctx.continuity_envelope,
        }

    return JSONResponse(status)


# =============================================================================
# Panel API
# =============================================================================

@app.put("/api/panel/{project_id}/{panel_name}")
async def save_panel(project_id: str, panel_name: str, request: Request):
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}

    s = ws.raw_state
    if panel_name == "story" and isinstance(body, dict):
        if s.story is None:
            from src.state.state_types import StoryState, StoryCore, StoryArc
            s.story = StoryState(
                step1=StoryCore(one_sentence=body.get("one_sentence", ""), tag=body.get("tag", "")),
                step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution=""),
            )
        else:
            if "one_sentence" in body:
                s.story.step1.one_sentence = body["one_sentence"]
            if "tag" in body:
                s.story.step1.tag = body["tag"]
    elif panel_name == "editor" and isinstance(body, dict):
        from src.state.state_types import DraftContent, ChapterDraft
        ch_num = body.get("chapter_number", 1)
        content = body.get("content", "")
        if ch_num not in s.drafts.chapters:
            s.drafts.chapters[ch_num] = ChapterDraft(chapter_number=ch_num)
        cd = s.drafts.chapters[ch_num]
        now = datetime.now().isoformat()
        cd.draft = DraftContent(content=content, agent="user", timestamp=now)
        cd.word_count = len(content)
        cd.updated_at = now
    elif panel_name == "characters" and isinstance(body, dict):
        from src.state.state_types import Character, CharactersState
        if s.characters is None:
            s.characters = CharactersState(characters=[])
        action = body.get("_action", "")
        char_data = body.get("character", {})
        idx = body.get("_index", -1)
        if action == "add" and char_data:
            new_char = Character(
                name=char_data.get("name", ""),
                role=char_data.get("role", "配角"),
                identity="",
                personality=char_data.get("personality", ""),
                goal=char_data.get("goal", ""),
                conflict="",
                description="",
            )
            s.characters.characters.append(new_char)
        elif action == "update" and char_data and 0 <= idx < len(s.characters.characters):
            ch = s.characters.characters[idx]
            for key in ("name", "role", "personality", "goal"):
                if key in char_data:
                    setattr(ch, key, char_data[key])
        elif action == "delete" and 0 <= idx < len(s.characters.characters):
            s.characters.characters.pop(idx)
    elif panel_name == "world" and isinstance(body, dict):
        from src.state.state_types import WorldState, PowerSystem, Geography, Society, WorldHistory
        if s.world is None:
            s.world = WorldState(
                power_system=PowerSystem(system_name="", tiers=[], cultivation_rules="", power_limit=""),
                geography=Geography(),
                society=Society(),
                history=WorldHistory(),
            )
        ps = s.world.power_system
        if "system" in body:
            ps.system_name = body["system"]
        if "tiers" in body:
            tiers_val = body["tiers"]
            if isinstance(tiers_val, list):
                ps.tiers = tiers_val
            elif isinstance(tiers_val, str) and tiers_val.strip():
                ps.tiers = [t.strip() for t in tiers_val.replace("\n", ",").split(",") if t.strip()]
        if "cultivation_rules" in body:
            ps.cultivation_rules = body["cultivation_rules"]
    elif panel_name == "context" and isinstance(body, dict):
        # 动态上下文手动编辑：更新 DynamicContext 字段
        try:
            from src.agents.context import persist_context
            ctx_path = Path(ws._project_dir) / "data" / "context.json"
            ctx_data = {}
            if ctx_path.exists():
                with open(ctx_path, "r", encoding="utf-8") as f:
                    ctx_data = json.loads(f.read())
            # 合并手动编辑的字段
            for key, val in body.items():
                if not key.startswith("_"):
                    ctx_data[key] = val
            # 处理 foreshadows_add
            if "foreshadows_add" in body and isinstance(body["foreshadows_add"], list):
                unresolved = ctx_data.get("unresolved_foreshadows", [])
                for fs in body["foreshadows_add"]:
                    if fs and fs not in unresolved:
                        unresolved.append(fs)
                ctx_data["unresolved_foreshadows"] = unresolved
            # 持久化
            ctx_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ctx_path, "w", encoding="utf-8") as f:
                json.dump(ctx_data, f, ensure_ascii=False, indent=2)
            logger.info("Context updated for %s: %s", project_id, list(body.keys())[:5])
        except Exception as e:
            logger.error("Context save failed for %s: %s", project_id, e)
            return JSONResponse({"ok": False, "error": f"上下文保存失败: {e}"}, status_code=500)
    elif panel_name in ("outline", "review"):
        # AI 生成内容，前端通常不手动编辑；允许保存但记录警告
        logger.warning("Panel '%s' save requested but data is AI-managed (project: %s)", panel_name, project_id)
    else:
        return JSONResponse({"ok": False, "error": f"不支持的面板类型: {panel_name}"}, status_code=400)

    ws.save()
    log_panel_save(project_id, panel_name, list(body.keys())[:5] if isinstance(body, dict) else [])
    return JSONResponse({"ok": True, "panel": panel_name})


# =============================================================================
# Phase 3: Fact Ledger confirm/deny endpoints
# =============================================================================

@app.post("/api/panel/{project_id}/factledger/{fact_id}/confirm")
async def confirm_fact(project_id: str, fact_id: str):
    """Confirm a candidate fact in the Fact Ledger."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.fact_ledger import FactLedger
        ledger = FactLedger(ws)
        if ledger.confirm_fact(fact_id):
            ws.save()
            logger.info("[api] fact confirmed: %s", fact_id)
            return JSONResponse({"ok": True, "fact_id": fact_id})
        else:
            return JSONResponse({"ok": False, "error": "事实不存在"}, status_code=404)
    except Exception as e:
        logger.error("[api] fact confirm failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/panel/{project_id}/factledger/{fact_id}/deny")
async def deny_fact(project_id: str, fact_id: str):
    """Deny a candidate fact in the Fact Ledger."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.fact_ledger import FactLedger
        ledger = FactLedger(ws)
        if ledger.deny_fact(fact_id):
            ws.save()
            logger.info("[api] fact denied: %s", fact_id)
            return JSONResponse({"ok": True, "fact_id": fact_id})
        else:
            return JSONResponse({"ok": False, "error": "事实不存在"}, status_code=404)
    except Exception as e:
        logger.error("[api] fact deny failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 4B: Writing Rules API
# =============================================================================

@app.get("/api/rules/{project_id}")
def get_rules(project_id: str):
    """获取项目的写作规则"""
    from src.agents.writing_rules import WritingRulesManager

    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    manager = WritingRulesManager(ws._project_dir)
    rules = manager.get(project_id)
    return JSONResponse({"ok": True, "rules": rules.to_dict()})


@app.post("/api/rules/{project_id}")
async def save_rules(project_id: str, request: Request):
    """保存/更新项目的写作规则"""
    from src.agents.writing_rules import WritingRules, WritingRulesManager

    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    rules = WritingRules.from_dict(body)
    rules.project_id = project_id

    manager = WritingRulesManager(ws._project_dir)
    ok = manager.save(rules)

    prompt_snippet = manager.inject_into_prompt(rules) if ok else ""
    return JSONResponse({
        "ok": ok,
        "rules": rules.to_dict() if ok else {},
        "prompt_snippet": prompt_snippet,
    })


# =============================================================================
# Phase 4B: Inspire API (灵感反推)
# =============================================================================

@app.post("/api/inspire")
async def inspire_api(request: Request):
    """灵感反推：从简短想法生成结构化写作灵感"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    seed = body.get("seed", "").strip()
    if not seed:
        return JSONResponse({"ok": False, "error": "请提供灵感想法"}, status_code=400)

    import asyncio
    from src.agents.inspire import inspire as do_inspire

    try:
        result = await asyncio.to_thread(do_inspire, seed)
        if "error" in result and result.get("story_core", {}).get("one_sentence") == seed:
            # Real failure (not just fallback)
            return JSONResponse({
                "ok": False,
                "error": result.get("error", "生成失败"),
                "partial": result,
            }, status_code=500)
        ok = "error" not in result
        return JSONResponse({"ok": ok, "data": result})
    except Exception as e:
        logger.exception("Inspire API 调用失败: seed=%s", seed[:50])
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/inspire/adopt")
async def inspire_adopt(request: Request):
    """采纳灵感反推结果，创建新项目"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    data = body.get("data", {})
    platform = body.get("platform", "起点")

    if not data or not data.get("story_core"):
        return JSONResponse({"ok": False, "error": "缺少故事核心数据"}, status_code=400)

    story_core = data.get("story_core", {})
    name = story_core.get("one_sentence", "新项目")[:40].strip()

    ws = Workspace.create(name=name, platform=platform,
                          seed_idea=story_core.get("one_sentence", ""))
    ws.save()

    # 填充灵感反推数据到 state
    s = ws.raw_state
    from src.state.state_types import StoryState, StoryCore, StoryArc
    s.story = StoryState(
        step1=StoryCore(
            one_sentence=story_core.get("one_sentence", ""),
            tag=story_core.get("tag", ""),
        ),
        step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution=""),
    )

    # 填充角色
    characters_data = data.get("main_characters", [])
    if characters_data:
        from src.state.state_types import Character, CharactersState
        chars = [
            Character(
                name=c.get("name", ""),
                role=c.get("role", "配角"),
                identity="",
                personality=c.get("personality", ""),
                goal=c.get("goal", ""),
                conflict="",
                description="",
            )
            for c in characters_data[:3]
        ]
        s.characters = CharactersState(characters=chars)

    # 填充世界观
    wb = data.get("world_building", {})
    if wb:
        from src.state.state_types import WorldState, PowerSystem, Geography, Society, WorldHistory
        s.world = WorldState(
            power_system=PowerSystem(
                system_name=wb.get("power_system", ""),
                tiers=[],
                cultivation_rules="",
                power_limit="",
            ),
            geography=Geography(
                major_locations=[{"name": loc.strip(), "description": "", "significance": ""}
                                 for loc in wb.get("major_locations", "").split("；")
                                 if loc.strip()],
            ),
            society=Society(
                factions=[{"name": f.strip(), "description": "", "alignment": ""}
                          for f in wb.get("factions", "").split("；")
                          if f.strip()],
            ),
            history=WorldHistory(),
        )

    # 填充章纲预览
    outline_data = data.get("outline_preview", [])
    if outline_data:
        from src.state.state_types import ChapterOutlineState, ChapterOutline
        chapters = []
        for i, ch in enumerate(outline_data[:3], 1):
            chapters.append(ChapterOutline(
                chapter_number=i,
                chapter_title=ch.get("chapter_title", f"第{i}章"),
                core_event=ch.get("core_event", ""),
                character_states="",
                story_progression="",
            ))
        s.chapter_outline = ChapterOutlineState(
            total_chapters=len(chapters),
            chapters=chapters,
        )

    # 保存写作规则（如果有的话）
    if data.get("writing_rules"):
        from src.agents.writing_rules import WritingRules, WritingRulesManager
        try:
            rules = WritingRules.from_dict(data["writing_rules"])
            rules.project_id = ws.project_id
            manager = WritingRulesManager(ws._project_dir)
            manager.save(rules)
        except Exception as e:
            logger.warning("Inspire adopt: 写作规则保存失败: %s", e)

    ws.save()
    ws.build_context_cache()
    _v2_ws[ws.project_id] = ws

    from dataclasses import asdict
    return JSONResponse({
        "ok": True,
        "project_id": ws.project_id,
        "project_name": ws.project_name,
        "dashboard": asdict(ws.get_dashboard()),
    })


# =============================================================================
# Export
# =============================================================================

# =============================================================================
# Phase 6: Timeline API
# =============================================================================

@app.get("/api/timeline/{project_id}")
def get_timeline(project_id: str):
    """Get all timeline events for a project, sorted by story_time."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.timeline import TimelineManager
        mgr = TimelineManager(project_id)
        events = [e.to_dict() for e in mgr.get_timeline()]
        return JSONResponse({"ok": True, "events": events})
    except Exception as e:
        logger.error("[api] timeline fetch failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/timeline/{project_id}")
async def add_timeline_event(project_id: str, request: Request):
    """Manually add a timeline event."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        body = await request.json()
        from src.agents.timeline import TimelineManager, TimelineEvent
        mgr = TimelineManager(project_id)
        ev = TimelineEvent(
            project_id=project_id,
            description=body.get("description", ""),
            chapter_num=body.get("chapter_num", 0),
            story_time=body.get("story_time", ""),
            event_type=body.get("event_type", "plot"),
        )
        mgr.create(ev)
        return JSONResponse({"ok": True, "event": ev.to_dict()})
    except Exception as e:
        logger.error("[api] timeline create failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.put("/api/timeline/{project_id}/{event_id}")
async def update_timeline_event(project_id: str, event_id: str, request: Request):
    """Update a timeline event."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        body = await request.json()
        from src.agents.timeline import TimelineManager
        mgr = TimelineManager(project_id)
        allowed = ["description", "chapter_num", "story_time", "event_type"]
        updates = {k: v for k, v in body.items() if k in allowed}
        ok = mgr.update(event_id, **updates)
        return JSONResponse({"ok": ok})
    except Exception as e:
        logger.error("[api] timeline update failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/api/timeline/{project_id}/{event_id}")
def delete_timeline_event(project_id: str, event_id: str):
    """Delete a timeline event."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.timeline import TimelineManager
        mgr = TimelineManager(project_id)
        ok = mgr.delete(event_id)
        return JSONResponse({"ok": ok})
    except Exception as e:
        logger.error("[api] timeline delete failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/timeline/{project_id}/extract")
async def extract_timeline_events(project_id: str, request: Request):
    """Auto-extract timeline events from all confirmed chapters.
    Iterates over every chapter that has final content, runs LLM extraction
    (60s timeout → regex fallback), and returns the total new events added.
    """
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.timeline import TimelineManager
        mgr = TimelineManager(project_id)
        s = ws.raw_state
        total_new = 0
        chapters_processed = 0
        if s.drafts and s.drafts.chapters:
            for ch_num in sorted(s.drafts.chapters.keys()):
                cd = s.drafts.chapters[ch_num]
                content = ""
                if cd.final and cd.final.content:
                    content = cd.final.content
                elif cd.draft and cd.draft.content:
                    content = cd.draft.content
                if content and len(content) > 50:
                    new_events = mgr.auto_extract(content, ch_num)
                    if new_events:
                        total_new += len(new_events)
                        chapters_processed += 1
        return JSONResponse({
            "ok": True,
            "extracted": total_new,
            "chapters_processed": chapters_processed,
        })
    except Exception as e:
        logger.error("[api] timeline extract failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 6: Style Learner API
# =============================================================================

@app.get("/api/style/{project_id}")
def get_style_profile(project_id: str):
    """Get merged style profile for a project from confirmed chapters."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.style_learner import StyleLearner, StyleProfile
        s = ws.raw_state
        profiles = []
        if s.drafts and s.drafts.chapters:
            for ch_num in sorted(s.drafts.chapters.keys()):
                cd = s.drafts.chapters[ch_num]
                if cd.stage == "final":
                    content = ""
                    if cd.final and cd.final.content:
                        content = cd.final.content
                    elif cd.draft and cd.draft.content:
                        content = cd.draft.content
                    if content:
                        profiles.append(StyleLearner.analyze_chapter(content))
        merged = StyleLearner.merge_profiles(profiles) if profiles else StyleProfile()
        return JSONResponse({"ok": True, "profile": merged.to_dict()})
    except Exception as e:
        logger.error("[api] style profile fetch failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/style/{project_id}/analyze")
async def analyze_style_profile(project_id: str, request: Request):
    """Re-analyze style profile for a project.
    Re-computes the merged style profile from all confirmed chapters
    and returns the same shape as GET /api/style/{project_id}.
    """
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.style_learner import StyleLearner, StyleProfile
        s = ws.raw_state
        profiles = []
        if s.drafts and s.drafts.chapters:
            for ch_num in sorted(s.drafts.chapters.keys()):
                cd = s.drafts.chapters[ch_num]
                content = ""
                if cd.final and cd.final.content:
                    content = cd.final.content
                elif cd.draft and cd.draft.content:
                    content = cd.draft.content
                if content and len(content) > 50:
                    profiles.append(StyleLearner.analyze_chapter(content))
        merged = StyleLearner.merge_profiles(profiles) if profiles else StyleProfile()
        return JSONResponse({
            "ok": True,
            "profile": merged.to_dict(),
            "chapters_analyzed": len(profiles),
        })
    except Exception as e:
        logger.error("[api] style analyze failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 6: Reference Library API
# =============================================================================

@app.get("/api/references/{project_id}")
def get_references(project_id: str, query: str = "", ref_type: str = ""):
    """Get reference materials. Optional filter by query and ref_type."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.references import ReferenceManager
        mgr = ReferenceManager(project_id)
        if query:
            refs = mgr.search(query)
        elif ref_type:
            refs = mgr.get_by_type(ref_type)
        else:
            refs = mgr.get_all()
        return JSONResponse({"ok": True, "references": [r.to_dict() for r in refs]})
    except Exception as e:
        logger.error("[api] references fetch failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/references/{project_id}")
async def create_reference(project_id: str, request: Request):
    """Create a new reference material."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        body = await request.json()
        from src.agents.references import ReferenceManager, ReferenceMaterial
        mgr = ReferenceManager(project_id)
        ref = ReferenceMaterial(
            project_id=project_id,
            title=body.get("title", ""),
            content=body.get("content", ""),
            ref_type=body.get("ref_type", "note"),
            tags=body.get("tags", []),
            source_url=body.get("source_url", ""),
        )
        mgr.create(ref)
        return JSONResponse({"ok": True, "reference": ref.to_dict()})
    except Exception as e:
        logger.error("[api] reference create failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.put("/api/references/{project_id}/{ref_id}")
async def update_reference(project_id: str, ref_id: str, request: Request):
    """Update a reference material."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        body = await request.json()
        from src.agents.references import ReferenceManager
        mgr = ReferenceManager(project_id)
        allowed = ["title", "content", "ref_type", "tags", "source_url"]
        updates = {k: v for k, v in body.items() if k in allowed}
        ok = mgr.update(ref_id, **updates)
        return JSONResponse({"ok": ok})
    except Exception as e:
        logger.error("[api] reference update failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/api/references/{project_id}/{ref_id}")
def delete_reference(project_id: str, ref_id: str):
    """Delete a reference material."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.references import ReferenceManager
        mgr = ReferenceManager(project_id)
        ok = mgr.delete(ref_id)
        return JSONResponse({"ok": ok})
    except Exception as e:
        logger.error("[api] reference delete failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 6: Doc Importer API
# =============================================================================

@app.post("/api/import/{project_id}")
async def import_document_file(project_id: str, file: UploadFile = File(...)):
    """Import a document file — supports .md, .txt, .docx via multipart form.

    Usage: curl -F "file=@doc.md" http://localhost:8000/api/import/{project_id}
    Returns parsed ImportResult (chapters, settings, materials, metadata) as JSON.
    """
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    if file.filename is None:
        return JSONResponse({"ok": False, "error": "请上传文件"}, status_code=400)

    original_name: str = file.filename
    suffix = Path(original_name).suffix.lower()

    # Validate supported format
    if suffix not in (".md", ".markdown", ".txt", ".docx"):
        return JSONResponse({
            "ok": False,
            "error": f"不支持的文件类型: {suffix}（支持 .md .txt .docx）",
        }, status_code=400)

    # Read raw bytes for size check
    raw_bytes = await file.read()
    if not raw_bytes:
        return JSONResponse({"ok": False, "error": "文件为空"}, status_code=400)

    file_size = len(raw_bytes)
    MAX_SIZE = 500 * 1024  # 500KB
    if file_size > MAX_SIZE:
        logger.warning(
            "[api] import large file: '%s' is %.1fKB, processing may be slow",
            original_name, file_size / 1024,
        )

    from src.utils.doc_importer import DocumentParser

    parser = DocumentParser()
    import tempfile

    try:
        if suffix == ".docx":
            # Save to temp file for docx parsing
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
            try:
                tmp.write(raw_bytes)
                tmp.close()
                result = parser.parse_file(tmp.name)
            finally:
                Path(tmp.name).unlink(missing_ok=True)
        else:
            # .md / .txt: decode content as UTF-8
            content = raw_bytes.decode("utf-8", errors="replace")
            result = parser.parse(content, original_name)

        # Check for parsing errors
        if result.metadata.get("error"):
            return JSONResponse({
                "ok": False,
                "error": result.metadata["error"],
            }, status_code=400)

        logger.info(
            "[api] import success: '%s' → %d chapters, %d settings, %d materials",
            original_name, len(result.chapters), len(result.settings), len(result.materials),
        )
        return JSONResponse({
            "ok": True,
            "file_name": original_name,
            "chapters": result.chapters,
            "settings": result.settings,
            "materials": result.materials,
            "metadata": result.metadata,
        })
    except Exception as e:
        logger.exception("[api] import failed for %s: %s", project_id, original_name)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 6: Usage Tracker API
# =============================================================================

@app.get("/api/usage/{project_id}")
def get_usage_stats(project_id: str):
    """Get LLM usage statistics for a project."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.utils.usage_tracker import UsageTracker
        tracker = UsageTracker()
        stats = tracker.get_project_stats(project_id)
        records = tracker.get_all_records(project_id)
        return JSONResponse({"ok": True, "stats": stats, "records": records[-100:]})
    except Exception as e:
        logger.error("[api] usage stats failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/usage")
def get_global_usage_stats():
    """Get LLM usage statistics across all projects."""
    try:
        from src.utils.usage_tracker import UsageTracker
        tracker = UsageTracker()
        stats = tracker.get_global_stats()
        records = tracker.get_all_records("")  # all records
        return JSONResponse({
            "ok": True,
            "stats": stats,
            "records": records[-100:],
        })
    except Exception as e:
        logger.error("[api] global usage stats failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Export
# =============================================================================

@app.get("/api/export/project/{project_id}")
def export_project(project_id: str, fmt: str = "md"):
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    s = ws.raw_state
    lines = [f"# {s.metadata.name}", f"平台: {s.metadata.platform}", ""]
    if s.story:
        lines.append(f"## 故事\n{s.story.step1.one_sentence}\n")
    if s.characters and s.characters.characters:
        lines.append("## 角色")
        for c in s.characters.characters:
            lines.append(f"- **{c.name}** ({c.role}): {c.personality} | 目标: {c.goal}")
        lines.append("")
    if s.world:
        lines.append(f"## 世界观\n力量体系: {s.world.power_system.system_name}\n")
    if s.chapter_outline:
        lines.append(f"## 章纲 ({s.chapter_outline.total_chapters}章)")
        for ch in s.chapter_outline.chapters:
            lines.append(f"- 第{ch.chapter_number}章: {ch.chapter_title}")
        lines.append("")
    if s.drafts and s.drafts.chapters:
        lines.append("## 正文")
        for ch_num in sorted(s.drafts.chapters.keys()):
            cd = s.drafts.chapters[ch_num]
            text = cd.final.content if cd.final else cd.draft.content if cd.draft else ""
            lines.append(f"\n### 第{ch_num}章 ({cd.word_count}字)\n{text[:5000]}")
        lines.append("")

    content = "\n".join(lines)
    log_export(project_id, fmt)
    return JSONResponse({"content": content, "fmt": fmt})


# =============================================================================
# Phase 4A: GlobalForeshadow API
# =============================================================================

@app.get("/api/foreshadows/{project_id}")
def list_foreshadows(project_id: str):
    """List all global foreshadows for a project."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.foreshadow import ForeshadowManager
        mgr = ForeshadowManager(ws)
        data = mgr.get_kanban_data()
        all_fs = [f.to_dict() for f in mgr.get_all()]
        return JSONResponse({"ok": True, "kanban": data, "all": all_fs})
    except Exception as e:
        logger.error("[api] foreshadows list failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/foreshadows/{project_id}")
async def create_foreshadow(project_id: str, request: Request):
    """Create a new global foreshadow."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        body = await request.json()
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow
        mgr = ForeshadowManager(ws)
        fs = GlobalForeshadow(
            project_id=project_id,
            title=body.get("title", ""),
            description=body.get("description", ""),
            type=body.get("type", "plot"),
            status=body.get("status", "planned"),
            planted_chapter=body.get("planted_chapter", 0),
            callback_chapters=body.get("callback_chapters", []),
            resolved_chapter=body.get("resolved_chapter", 0),
            urgency=body.get("urgency", 3),
            expected_callback_range=body.get("expected_callback_range", ""),
            deadline_chapter=body.get("deadline_chapter", 0),
        )
        mgr.create(fs)
        ws.save()
        return JSONResponse({"ok": True, "foreshadow": fs.to_dict()})
    except Exception as e:
        logger.error("[api] foreshadow create failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.put("/api/foreshadows/{project_id}/{fs_id}")
async def update_foreshadow(project_id: str, fs_id: str, request: Request):
    """Update a global foreshadow."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        body = await request.json()
        from src.agents.foreshadow import ForeshadowManager
        mgr = ForeshadowManager(ws)
        allowed = ["title", "description", "type", "status", "planted_chapter",
                    "callback_chapters", "resolved_chapter", "urgency",
                    "expected_callback_range", "deadline_chapter"]
        updates = {k: v for k, v in body.items() if k in allowed}
        ok = mgr.update(fs_id, **updates)
        ws.save()
        return JSONResponse({"ok": ok})
    except Exception as e:
        logger.error("[api] foreshadow update failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/api/foreshadows/{project_id}/{fs_id}")
def delete_foreshadow(project_id: str, fs_id: str):
    """Delete a global foreshadow."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.foreshadow import ForeshadowManager
        mgr = ForeshadowManager(ws)
        ok = mgr.delete(fs_id)
        ws.save()
        return JSONResponse({"ok": ok})
    except Exception as e:
        logger.error("[api] foreshadow delete failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/foreshadows/{project_id}/extract")
def extract_foreshadows(project_id: str, chapter_num: int = 1):
    """Trigger LLM foreshadow extraction for a specific chapter."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        ch = ws.raw_state.drafts.chapters.get(chapter_num)
        content = ""
        if ch:
            if ch.final and ch.final.content:
                content = ch.final.content
            elif ch.draft and ch.draft.content:
                content = ch.draft.content
        if not content:
            return JSONResponse({"ok": False, "error": f"第{chapter_num}章无内容"}, status_code=400)
        from src.agents.foreshadow import ForeshadowManager
        mgr = ForeshadowManager(ws)
        new_fs = mgr.extract_from_chapter(content, chapter_num, project_id)
        mgr.apply_extraction(new_fs, chapter_num)
        ws.save()
        return JSONResponse({"ok": True, "extracted": len(new_fs),
                            "foreshadows": [f.to_dict() for f in new_fs]})
    except Exception as e:
        logger.error("[api] foreshadow extract failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 4A: StateTable API
# =============================================================================

@app.get("/api/statetable/{project_id}")
def list_state_table(project_id: str):
    """Get all character states for a project."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.state_table import StateTable
        table = StateTable(ws)
        states = [s.to_dict() for s in table.list_states(project_id)]
        # Include timeline for each character
        timelines = {}
        for s in table.list_states(project_id):
            tl = table.get_character_timeline(s.character_id)
            timelines[s.character_id] = [t.to_dict() for t in tl]
        return JSONResponse({"ok": True, "states": states, "timelines": timelines})
    except Exception as e:
        logger.error("[api] state_table list failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 4A: ItemLedger API
# =============================================================================

@app.get("/api/itemledger/{project_id}/{item_id}/history")
def get_item_history(project_id: str, item_id: str):
    """Get transaction history for a specific item by item_id."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.item_ledger import ItemLedger
        ledger = ItemLedger(ws)
        history = ledger.get_item_history(item_id)
        holder = ledger.get_current_holder(item_id)
        return JSONResponse({
            "ok": True,
            "item_id": item_id,
            "current_holder": holder,
            "history": [t.to_dict() for t in history],
        })
    except Exception as e:
        logger.error("[api] item history failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/itemledger/{project_id}")
def list_item_ledger(project_id: str):
    """Get all item transactions for a project."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        from src.agents.item_ledger import ItemLedger
        ledger = ItemLedger(ws)
        all_txs = [t.to_dict() for t in ledger.get_all_transactions()]
        # Group by item name for summary
        items_summary = {}
        for tx in ledger.get_all_transactions():
            if tx.item_name not in items_summary:
                items_summary[tx.item_name] = {
                    "current_holder": ledger.get_current_holder(tx.item_name),
                    "transaction_count": 0,
                }
            items_summary[tx.item_name]["transaction_count"] += 1
        return JSONResponse({
            "ok": True,
            "transactions": all_txs,
            "items": items_summary,
        })
    except Exception as e:
        logger.error("[api] item ledger list failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Phase 5: SQLite Migration & Snapshots & Rich Export
# =============================================================================

@app.post("/api/migrate")
def migrate_to_sqlite():
    """Trigger migration of all existing JSON projects to SQLite."""
    try:
        from src.state.migrate_to_sqlite import migrate_all
        result = migrate_all(projects_dir="projects", db_path="projects/writesync.db")
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        logger.exception("Migration failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/snapshots/{project_id}")
async def create_snapshot(project_id: str, request: Request):
    """Create a manual snapshot. Form field: name (optional)."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        body = {}
    name = body.get("name", "").strip()

    try:
        from src.state.snapshot import SnapshotManager
        sm = SnapshotManager(_pm._db)

        # Serialize current state
        state_dict = _pm._serialize(ws.raw_state)
        if name:
            snap_id = sm.create_manual_snapshot(project_id, name, state_dict)
        else:
            snap_id = sm.create_auto_snapshot(project_id, state_dict)

        return JSONResponse({"ok": True, "snapshot_id": snap_id})
    except Exception as e:
        logger.exception("Snapshot creation failed for %s", project_id)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/snapshots/{project_id}")
def list_snapshots(project_id: str):
    """List all snapshots for a project."""
    try:
        from src.state.snapshot import SnapshotManager
        sm = SnapshotManager(_pm._db)
        snaps = sm.list_snapshots(project_id)
        result = []
        for s in snaps:
            result.append({
                "id": s.id,
                "name": s.name,
                "created_at": s.created_at,
                "chapter_count": s.chapter_count,
                "word_count": s.word_count,
            })
        return JSONResponse({"ok": True, "snapshots": result})
    except Exception as e:
        logger.exception("Snapshot list failed for %s", project_id)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/snapshots/{project_id}/{snapshot_id}/restore")
def restore_snapshot(project_id: str, snapshot_id: str):
    """Restore a project from a snapshot."""
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    try:
        from src.state.snapshot import SnapshotManager
        sm = SnapshotManager(_pm._db)
        state_dict = sm.restore_snapshot(project_id, snapshot_id)
        if state_dict is None:
            return JSONResponse({"ok": False, "error": "快照不存在或已损坏"}, status_code=404)

        # Reconstruct state from snapshot
        restored_state = _pm._reconstruct(state_dict, WriteSyncState)
        ws._state = restored_state
        ws.save()
        ws.build_context_cache()

        logger.info("Snapshot %s restored for project %s", snapshot_id, project_id)
        return JSONResponse({"ok": True, "snapshot_id": snapshot_id,
                            "project_id": project_id})
    except Exception as e:
        logger.exception("Snapshot restore failed for %s", project_id)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/api/snapshots/{project_id}/{snapshot_id}")
def delete_snapshot(project_id: str, snapshot_id: str):
    """Delete a snapshot."""
    try:
        from src.state.snapshot import SnapshotManager
        sm = SnapshotManager(_pm._db)
        ok = sm.delete_snapshot(snapshot_id)
        return JSONResponse({"ok": ok})
    except Exception as e:
        logger.exception("Snapshot delete failed for %s", snapshot_id)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/export/{project_id}")
def export_rich(project_id: str, fmt: str = "md"):
    """Rich export endpoint. fmt=html | json | md (default: md).

    Returns file download or content.
    """
    ws = _get_ws(project_id)
    if ws is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)

    fmt_lower = fmt.lower().strip()

    try:
        if fmt_lower == "html":
            from src.utils.export_html import export_to_html
            output_path = export_to_html(ws.raw_state)
            with open(output_path, "r", encoding="utf-8") as f:
                content = f.read()
            log_export(project_id, "html")
            return JSONResponse({"content": content, "fmt": "html", "file": output_path})

        elif fmt_lower == "json":
            from src.utils.export_json import export_full_backup
            output_path = export_full_backup(ws.raw_state)
            with open(output_path, "r", encoding="utf-8") as f:
                content = f.read()
            log_export(project_id, "json")
            return JSONResponse({"content": content, "fmt": "json", "file": output_path,
                                "content_type": "application/json"})

        else:
            # Default to markdown export (existing behavior)
            return export_project(project_id, fmt)

    except Exception as e:
        logger.exception("Export failed for %s fmt=%s", project_id, fmt_lower)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# =============================================================================
# Provider Management API
# =============================================================================

@app.get("/api/providers")
def list_providers():
    """List all configured providers (api_key masked)."""
    pm = get_provider_manager()
    return JSONResponse(pm.registry.to_dict(mask_key=True))


@app.post("/api/providers")
async def add_provider(request: Request):
    """Add a new provider."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    required = ["name", "provider_type", "base_url"]
    for field in required:
        if not body.get(field):
            return JSONResponse({"ok": False, "error": f"Missing field: {field}"}, status_code=400)

    config = AIProviderConfig(
        name=body["name"],
        provider_type=body["provider_type"],
        base_url=body["base_url"],
        api_key=body.get("api_key", ""),
        default_model=body.get("default_model", ""),
        max_tokens=body.get("max_tokens", 4096),
        context_window=body.get("context_window", 128000),
        is_default=body.get("is_default", False),
    )
    pm = get_provider_manager()
    pm.add_provider(config)
    return JSONResponse({"ok": True, "provider": config.to_dict(mask_key=True)})


@app.put("/api/providers/{name}")
async def update_provider(name: str, request: Request):
    """Update an existing provider."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    pm = get_provider_manager()
    existing = pm.get_by_name(name)
    if existing is None:
        return JSONResponse({"ok": False, "error": "Provider not found"}, status_code=404)

    # Update allowed fields
    allowed = {"base_url", "api_key", "default_model", "max_tokens", "context_window", "is_default"}
    updates = {k: v for k, v in body.items() if k in allowed}
    ok = pm.update_provider(name, **updates)
    if not ok:
        return JSONResponse({"ok": False, "error": "Update failed"}, status_code=500)

    updated = pm.get_by_name(name)
    return JSONResponse({"ok": True, "provider": updated.to_dict(mask_key=True) if updated else None})


@app.delete("/api/providers/{name}")
def delete_provider(name: str):
    """Remove a provider."""
    pm = get_provider_manager()
    removed = pm.remove_provider(name)
    return JSONResponse({"ok": removed})


@app.post("/api/providers/{name}/test")
def test_provider(name: str):
    """Test connection to a provider."""
    pm = get_provider_manager()
    config = pm.get_by_name(name)
    if config is None:
        return JSONResponse({"ok": False, "error": "Provider not found"}, status_code=404)
    result = pm.test_connection(config)
    return JSONResponse(result)


# ── Prompt Library API (Phase 1.2) ─────────────────────────────────────────

@app.get("/api/prompts")
def list_prompts():
    """List all available prompt templates with metadata."""
    from src.agents.prompts.manager import PromptManager
    pm = PromptManager()
    return JSONResponse({
        "agents": pm.list_agents_detail(),
        "genre_packs": pm.list_genre_packs(),
    })


@app.get("/api/prompts/{agent_name}")
def get_prompt(agent_name: str, genre: str = ""):
    """Get a specific prompt template (raw + rendered with optional genre pack)."""
    from src.agents.prompts.manager import PromptManager
    pm = PromptManager()
    result = pm.get_prompt_detail(agent_name, genre_pack=genre if genre else None)
    if result is None:
        return JSONResponse({"ok": False, "error": f"Agent '{agent_name}' not found"}, status_code=404)
    return JSONResponse({"ok": True, **result})


@app.post("/api/prompts/customize")
def customize_prompt(request: Request):
    """Save user-customized prompt override."""
    import json as _json
    try:
        body = _json.loads(request.body())
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    agent = body.get("agent")
    content = body.get("content", "")
    if not agent or not content:
        return JSONResponse({"ok": False, "error": "agent and content required"}, status_code=400)

    from src.agents.prompts.manager import PromptManager
    pm = PromptManager()
    pm.save_custom_prompt(agent, content)
    return JSONResponse({"ok": True, "agent": agent})
