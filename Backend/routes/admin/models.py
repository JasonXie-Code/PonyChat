from fastapi import APIRouter, HTTPException
from ...config import logger, model_manager

router = APIRouter()

@router.get("/models/config")
async def get_all_models_config():
    """获取所有模型详细配置"""
    try:
        return {
            "active_model_id": model_manager.get_active_model_id(),
            "models": model_manager.get_models()
        }
    except Exception as e:
        logger.error(f"获取模型配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/models/config")
async def update_model_config(payload: dict):
    """更新某个模型的配置或切换活动模型"""
    try:
        action = payload.get("action")
        if action == "set_active":
            model_id = payload.get("model_id")
            if model_manager.set_active_model(model_id):
                return {"success": True, "message": f"已切换活动模型为 {model_id}"}
            raise HTTPException(status_code=400, detail="模型不存在")
        
        elif action == "update":
            model_id = payload.get("model_id")
            updates = payload.get("updates")
            if model_manager.update_model(model_id, updates):
                return {"success": True, "message": "模型配置已更新"}
            raise HTTPException(status_code=400, detail="模型不存在")
            
        elif action == "add":
            model_data = payload.get("model_data")
            new_id = model_manager.add_model(model_data)
            return {"success": True, "message": "新模型已添加", "id": new_id}
            
        elif action == "delete":
            model_id = payload.get("model_id")
            if model_manager.delete_model(model_id):
                return {"success": True, "message": "模型已删除"}
            raise HTTPException(status_code=400, detail="删除失败")
            
        raise HTTPException(status_code=400, detail="Invalid action")
    except Exception as e:
        logger.error(f"操作模型配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/models/test")
async def test_model_connectivity(payload: dict):
    """测试模型 API 连接性"""
    try:
        # 兼容性提取：支持前端可能传来的多种命名方式
        provider = payload.get("provider") or payload.get("type")
        api_key = payload.get("api_key")
        base_url = payload.get("base_url") or payload.get("endpoint")
        model_name = payload.get("model_name") or payload.get("model_id")
        
        # 记录测试请求
        logger.info(f"🧪 开始测试模型连接: {model_name or '未指定'} ({provider})")
        
        # 构造临时的测试配置
        test_config = {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name
        }
        
        # 调用模型管理器
        success, message = await model_manager.test_connection(test_config)
        
        if success:
            return {"success": True, "message": "连接测试成功！API 可正常通信。"}
        else:
            return {"success": False, "message": f"连接失败: {message}"}
            
    except Exception as e:
        logger.error(f"模型测试失败: {e}")
        return {"success": False, "message": f"系统错误: {str(e)}"}
