import asyncio
from fastapi import APIRouter, Body, HTTPException
from ..config import model_manager, logger

router = APIRouter(prefix="/api")

@router.get("/models")
async def get_models():
    """获取模型列表（管理后台用）。"""
    return {
        "status": "success",
        "models": model_manager.get_visible_models_for_client()
    }

def _is_draw_model(m: dict) -> bool:
    """与前端/系统一致的绘图模型判定：is_draw、tags、名称含 image"""
    if m.get("is_draw") is True:
        return True
    tags = [str(t) for t in (m.get("tags") or [])]
    if any("绘图" in t or "文生图" in t for t in tags):
        return True
    name = f"{m.get('id', '')} {m.get('model_name', '')} {m.get('name', '')}".lower()
    return "image" in name


@router.post("/models/test_all")
async def test_all_models(payload: dict = Body(None)):
    """批量测试可见模型的可用性。payload.mode: 'chat'|'draw'|'all'，默认 chat（与对话模型大厅一致）。"""
    payload = payload or {}
    mode = (payload.get("mode") or "chat").lower()
    models = model_manager.get_models()
    # 与模型大厅保持一致：hidden=true 和 enabled=false 都不参与批量测试
    visible_models = [m for m in models if not m.get("hidden", False) and m.get("enabled") is not False]
    if mode == "chat":
        visible_models = [m for m in visible_models if not _is_draw_model(m)]
    elif mode == "draw":
        visible_models = [m for m in visible_models if _is_draw_model(m)]
    # mode == "all" 或不认识的值：保持全部可见模型

    async def test_one(model):
        model_id = model.get("id", "")
        try:
            success, msg = await model_manager.test_connection(model)
            return {"id": model_id, "available": success, "message": msg}
        except Exception as e:
            return {"id": model_id, "available": False, "message": str(e)}
    
    results = await asyncio.gather(*[test_one(m) for m in visible_models])
    
    logger.info(f"🧪 批量测试完成: {len(results)} 个模型, "
                f"{sum(1 for r in results if r['available'])} 个可用")
    
    return {
        "status": "success",
        "results": {r["id"]: {"available": r["available"], "message": r["message"]} for r in results}
    }


@router.post("/models/test_one_detailed")
async def test_one_model_detailed(payload: dict = Body(None)):
    """测试单个模型并返回结构化错误详情。payload: {id?: str, config?: dict}"""
    payload = payload or {}
    model_id = payload.get("id")
    model_cfg = payload.get("config")

    target_model = None
    if isinstance(model_cfg, dict):
        target_model = model_cfg
    elif model_id:
        target_model = next((m for m in model_manager.get_models() if m.get("id") == model_id), None)

    if not target_model:
        raise HTTPException(status_code=400, detail="请提供有效的模型 id 或 config")

    result = await model_manager.test_connection_detailed(target_model)
    return {
        "status": "success",
        "model_id": target_model.get("id"),
        "result": result,
    }

