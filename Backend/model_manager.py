import json
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import save_chat_debug_log

logger = logging.getLogger(__name__)

# 全局默认模型 ID（唯一约定；业务侧请用 get_active_model / get_user_active_model / get_default_active_model，勿再硬编码其他 id）
# 含义：① model_config.json 的 active_model 回退 ② 用户无偏好或偏好无效 ③ 清单中 active 缺失/禁用时的解析结果
DEFAULT_FALLBACK_MODEL_ID = "deepseek-flash"

CONF_DIR = Path(__file__).parent / "conf"
CONFIG_FILE = CONF_DIR / "model_config.json"
CUSTOM_FRAGMENT_REL = "models/custom.json"


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写入 JSON 文件。"""
    tmp_path = path.parent / (path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.error(f"Failed to write JSON {path}: {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise


def _expand_env_placeholders(value: Any) -> Any:
    """Expand ${ENV_NAME} strings in model config fragments at runtime."""
    if isinstance(value, dict):
        return {k: _expand_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_placeholders(v) for v in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def merge_model_sources(conf_dir: Path, manifest: Dict[str, Any]) -> tuple:
    """合并 model_sources 中各文件内的 models；返回 (merged_models, id_to_path)。"""
    merged: List[Dict[str, Any]] = []
    id_to_path: Dict[str, Path] = {}
    for rel in manifest.get("model_sources", []):
        p = (conf_dir / rel).resolve()
        if not p.exists():
            logger.warning("Model source file missing: %s", p)
            continue
        frag = _expand_env_placeholders(_read_json(p))
        for m in frag.get("models", []):
            mid = m.get("id")
            if not mid:
                continue
            if mid in id_to_path:
                logger.warning("Duplicate model id %s in config sources (skipped)", mid)
                continue
            id_to_path[mid] = p
            merged.append(m)
    return merged, id_to_path


def load_merged_model_config() -> Dict[str, Any]:
    """读取清单并合并各供应商片段，与旧版单文件结构一致（含 models 列表）。"""
    if not CONFIG_FILE.exists():
        return {}
    raw = _expand_env_placeholders(_read_json(CONFIG_FILE))
    if raw.get("model_sources"):
        models, _ = merge_model_sources(CONF_DIR, raw)
        return {
            "active_model": raw.get("active_model", ""),
            "models": models,
            "custom_models": raw.get("custom_models", []),
        }
    return raw


class ModelManager:
    # 🔧 [优化] 配置缓存 TTL（秒）
    CACHE_TTL = 30
    
    def __init__(self):
        self._config_cache = None
        self._cache_time = 0
        self._file_mtime = 0
        self._legacy_single_file = False
        self._model_id_to_source: Dict[str, Path] = {}
        self.config = self._load_config()
        
        # 模型大厅展示字段必须只来自模型配置（清单 + 各供应商片段），避免运行时偷偷注入价格/免费状态。

    def _aggregate_config_mtime(self) -> float:
        """清单 + 各供应商片段任一改动即视为配置变更。"""
        try:
            mtimes = [CONFIG_FILE.stat().st_mtime]
            raw = _expand_env_placeholders(_read_json(CONFIG_FILE))
            if raw.get("model_sources"):
                for rel in raw["model_sources"]:
                    p = CONF_DIR / rel
                    if p.exists():
                        mtimes.append(p.stat().st_mtime)
        except Exception:
            return 0.0
        return max(mtimes) if mtimes else 0.0
    
    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效（未过期且文件未被修改）"""
        if self._config_cache is None:
            return False
        if time.time() - self._cache_time > self.CACHE_TTL:
            return False
        try:
            if self._aggregate_config_mtime() != self._file_mtime:
                return False
        except Exception:
            return False
        return True
    
    def _load_config(self) -> Dict[str, Any]:
        # 🔧 [优化] 使用缓存避免频繁文件 I/O
        if self._is_cache_valid():
            return self._config_cache
        
        if not CONFIG_FILE.exists():
            # 与仓库正式 DeepSeek 视觉片段对齐；冷启动仅一条模型，避免与 DEFAULT_FALLBACK_MODEL_ID 分叉
            default_model = {
                "id": DEFAULT_FALLBACK_MODEL_ID,
                "name": "DeepSeek V4 Flash Vision",
                "type": "openai",
                "endpoint": "https://api.deepseek.com",
                "model_name": "deepseek-flash",
                "api_key": "${PONYCHAT_DEEPSEEK_API_KEY}",
                "supports_vision": True,
                "uses_v4_thinking_api": True,
                "enable_thinking": True,
                "options": {"reasoning_effort": "low"},
                "enabled": True,
            }
            models_dir = CONF_DIR / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(models_dir / "deepseek.json", {"models": [default_model]})
            _atomic_write_json(models_dir / "custom.json", {"models": []})
            manifest = {
                "active_model": DEFAULT_FALLBACK_MODEL_ID,
                "model_sources": [
                    "models/deepseek.json",
                    "models/custom.json",
                ],
                "custom_models": []
            }
            _atomic_write_json(CONFIG_FILE, manifest)
            merged, id_map = merge_model_sources(CONF_DIR, manifest)
            self._legacy_single_file = False
            self._model_id_to_source = id_map
            default_config = {
                "active_model": manifest["active_model"],
                "models": merged,
                "custom_models": [],
                "model_sources": manifest["model_sources"],
            }
            self._update_cache(default_config)
            return default_config
        
        try:
            raw = _read_json(CONFIG_FILE)
            if raw.get("model_sources"):
                models, id_map = merge_model_sources(CONF_DIR, raw)
                self._legacy_single_file = False
                self._model_id_to_source = id_map
                config = {
                    "active_model": raw.get("active_model", ""),
                    "models": models,
                    "custom_models": raw.get("custom_models", []),
                    "model_sources": raw["model_sources"],
                }
            else:
                self._legacy_single_file = True
                self._model_id_to_source = {}
                for m in raw.get("models", []):
                    mid = m.get("id")
                    if mid:
                        self._model_id_to_source[mid] = CONFIG_FILE.resolve()
                config = raw
            self._update_cache(config)
            return config
        except Exception as e:
            logger.error(f"Failed to load model config: {e}")
            return {}
    
    def _update_cache(self, config: Dict[str, Any]):
        """更新缓存"""
        self._config_cache = config
        self._cache_time = time.time()
        try:
            self._file_mtime = self._aggregate_config_mtime()
        except Exception:
            self._file_mtime = 0

    def _save_config(self):
        self._save_config_to_file(self.config)

    def _save_manifest_only(self):
        """仅更新清单中的 active_model 等，不重写各供应商片段。"""
        try:
            manifest = {
                "active_model": self.config.get("active_model", ""),
                "model_sources": self.config.get("model_sources", []),
                "custom_models": self.config.get("custom_models", []),
            }
            _atomic_write_json(CONFIG_FILE, manifest)
            self._update_cache(self.config)
        except Exception as e:
            logger.error(f"Failed to save model manifest: {e}")

    def _persist_fragment_models(self, models: List[Dict[str, Any]], model_sources: List[str]) -> None:
        """按供应商文件写回各片段；未绑定 id 的新模型归入 custom.json。"""
        by_path: Dict[Path, List[Dict[str, Any]]] = {}
        for m in models:
            mid = m.get("id")
            if not mid:
                continue
            path = self._model_id_to_source.get(mid)
            if path is None:
                path = (CONF_DIR / CUSTOM_FRAGMENT_REL).resolve()
                self._model_id_to_source[mid] = path
            by_path.setdefault(path, []).append(m)
        for rel in model_sources:
            p = (CONF_DIR / rel).resolve()
            items = by_path.get(p, [])
            _atomic_write_json(p, {"models": items})

    def _ensure_custom_fragment_for_new_model(self, model_id: str) -> None:
        """运行时新增模型：写入 models/custom.json 并加入 model_sources。"""
        srcs = self.config.setdefault("model_sources", [])
        if CUSTOM_FRAGMENT_REL not in srcs:
            srcs.append(CUSTOM_FRAGMENT_REL)
        p = (CONF_DIR / CUSTOM_FRAGMENT_REL).resolve()
        if not p.exists():
            _atomic_write_json(p, {"models": []})
        self._model_id_to_source[model_id] = p

    def _save_config_to_file(self, config: Dict[str, Any]) -> None:
        """清单格式：manifest + 各片段；旧版单文件仍只写 model_config.json。"""
        try:
            if self._legacy_single_file or not config.get("model_sources"):
                out = dict(config)
                out.pop("model_sources", None)
                _atomic_write_json(CONFIG_FILE, out)
                self._update_cache(config)
                return
            manifest = {
                "active_model": config.get("active_model", ""),
                "model_sources": config.get("model_sources", []),
                "custom_models": config.get("custom_models", []),
            }
            _atomic_write_json(CONFIG_FILE, manifest)
            self._persist_fragment_models(config.get("models", []), config.get("model_sources", []))
            self._update_cache(config)
        except Exception as e:
            logger.error(f"Failed to save model config: {e}")

    def get_models(self) -> List[Dict[str, Any]]:
        """返回全量模型列表（含隐藏模型），供内部任务和管理端使用。"""
        self.config = self._load_config()
        return self.config.get("models", [])

    def get_visible_models(self) -> List[Dict[str, Any]]:
        """
        返回可在模型大厅展示给用户的模型列表。
        过滤规则：
          - hidden=true   → 不展示（但后端仍可调用）
          - enabled=false → 不展示（且后端也不允许调用）
        """
        self.config = self._load_config()
        result = []
        for m in self.config.get("models", []):
            if m.get("hidden", False):
                continue
            if m.get("enabled", True) is False:
                continue
            result.append(m)
        return result

    @staticmethod
    def _model_identity_text(model: Dict[str, Any]) -> str:
        return f"{model.get('id', '')} {model.get('model_name', '')} {model.get('name', '')} {model.get('endpoint', '')}".lower()

    def _supports_web_search(self, model: Dict[str, Any]) -> bool:
        return bool(model.get("supports_web_search"))

    def _supports_reasoning_effort(self, model: Dict[str, Any]) -> bool:
        return bool(model.get("supports_reasoning_effort"))

    def _supports_thinking_toggle(self, model: Dict[str, Any]) -> bool:
        return bool(model.get("supports_thinking_toggle"))

    def _supports_enable_thinking(self, model: Dict[str, Any]) -> bool:
        return bool(model.get("supports_enable_thinking"))

    def _build_config_schema(self, model: Dict[str, Any]) -> List[Dict[str, Any]]:
        schema: List[Dict[str, Any]] = []
        options = model.get("options") if isinstance(model.get("options"), dict) else {}
        default_temp = float(options.get("temperature", 0.7) or 0.7)
        default_max_tokens = int(options.get("max_tokens", 4096) or 4096)
        schema.append({
            "key": "temperature",
            "label": "温度",
            "description": "控制回复发散程度",
            "type": "float_slider",
            "min": 0.0,
            "max": 2.0,
            "step": 0.1,
            "default_float": round(default_temp, 2),
        })
        _max_tokens_cap = 16384
        schema.append({
            "key": "max_tokens",
            "label": "最大输出",
            "description": "限制单次回复最大输出 token 数",
            "type": "int_slider",
            "min": 256,
            "max": _max_tokens_cap,
            "step": 256,
            "default_int": min(default_max_tokens, _max_tokens_cap),
        })
        if self._supports_reasoning_effort(model):
            default_reasoning = str(
                options.get("reasoning_effort")
                or ("high" if model.get("supports_reasoning") else "")
            ).strip().lower() or "high"
            # 只有 Doubao/Seed 系列才显示 enable_thinking 开关（Gemini 无对应 API，用档位代替）
            if self._supports_thinking_toggle(model):
                schema.append({
                    "key": "enable_thinking",
                    "label": "启用思考",
                    "description": "关闭后模型直接回答，不进行推理（速度更快）",
                    "type": "boolean",
                    "default_bool": True,
                    "group": "thinking",
                })
            schema.append({
                "key": "reasoning_effort",
                "label": "思考档位",
                "description": "控制推理深度，档位越高回答越准确但耗时更长",
                "type": "enum",
                "default_string": default_reasoning,
                "group": "thinking",
                "options": [
                    {"value": "minimal", "label": "极低"},
                    {"value": "low", "label": "低"},
                    {"value": "medium", "label": "中"},
                    {"value": "high", "label": "高"},
                ],
            })
        if self._supports_enable_thinking(model):
            is_v4_thinking = bool(model.get("uses_v4_thinking_api"))
            # DeepSeek 双模型：通过切换 model_name 控制，无思考预算档位
            is_dual_model = bool(model.get("model_name_no_thinking"))
            think_on_name = model.get("model_name", "")
            think_off_name = model.get("model_name_no_thinking", "")
            if is_dual_model:
                desc = f"开启后调用 {think_on_name}"
            elif is_v4_thinking:
                desc = "关闭后非思考模式，响应更快、成本更低；开启为思考模式，支持 high/max 推理强度"
            else:
                desc = "开启后模型先推理再回答，效果更好，但耗时更长"
            schema.append({
                "key": "enable_thinking",
                "label": "启用思考",
                "description": desc,
                "type": "boolean",
                "default_bool": bool(model.get("enable_thinking", True)),
                "group": "thinking",
            })
            if is_v4_thinking:
                _def_eff = str(
                    options.get("reasoning_effort")
                    or "low"
                ).strip().lower()
                if _def_eff != "low":
                    _def_eff = "low"
                schema.append({
                    "key": "reasoning_effort",
                    "label": "思考强度",
                    "description": "统一使用 DeepSeek 视觉模型的 low 思考模式",
                    "type": "enum",
                    "default_string": _def_eff,
                    "group": "thinking",
                    "options": [
                        {"value": "low", "label": "低"},
                    ],
                })
            # 非双模型且非 V4 thinking 才显示 Qwen 式思考预算档位
            elif not is_dual_model:
                schema.append({
                    "key": "thinking_budget",
                    "label": "思考档位",
                    "description": "控制思考过程允许消耗的 token 数量（档位越高推理越深）",
                    "type": "enum",
                    "default_string": "auto",
                    "group": "thinking",
                    "options": [
                        {"value": "auto", "label": "自动"},
                        {"value": "low", "label": "低 4K"},
                        {"value": "medium", "label": "中 8K"},
                        {"value": "high", "label": "高 16K"},
                    ],
                })
        if self._supports_web_search(model):
            schema.append({
                "key": "web_search",
                "label": "联网搜索",
                "description": "允许模型按需调用联网工具",
                "type": "boolean",
                "default_bool": True,
            })
        return schema

    def build_client_model_info(self, model: Dict[str, Any]) -> Dict[str, Any]:
        options = model.get("options") if isinstance(model.get("options"), dict) else {}
        return {
            "id": model.get("id", ""),
            "name": model.get("name", "") or model.get("id", ""),
            "model_name": model.get("model_name"),
            "description": model.get("description"),
            "hidden": bool(model.get("hidden", False)),
            "is_draw": bool(model.get("is_draw", False)),
            "enabled": model.get("enabled", True) is not False,
            "is_default": bool(model.get("is_default", False)),
            "supports_vision": bool(model.get("supports_vision", False)),
            "supports_reasoning": bool(model.get("supports_reasoning", False)),
            "supports_tools": bool(model.get("supports_tools", False)),
            "supports_web_search": self._supports_web_search(model),
            "config_schema": self._build_config_schema(model),
            "default_options": {
                "temperature": options.get("temperature"),
                "max_tokens": options.get("max_tokens"),
                "reasoning_effort": options.get("reasoning_effort"),
            }
        }

    def get_visible_models_for_client(self) -> List[Dict[str, Any]]:
        return [self.build_client_model_info(m) for m in self.get_visible_models()]

    def get_active_model_id(self) -> str:
        m = self.get_active_model()
        return str(m.get("id", "")) if m else ""

    def get_active_model(self) -> Optional[Dict[str, Any]]:
        self.config = self._load_config()
        models = self.config.get("models", []) or []

        def _enabled(m: Optional[Dict[str, Any]]) -> bool:
            return m is not None and m.get("enabled") is not False

        active_id = str(self.config.get("active_model", "") or "").strip()
        cur = next((x for x in models if x.get("id") == active_id), None)
        if _enabled(cur):
            return cur
        fb = next((x for x in models if x.get("id") == DEFAULT_FALLBACK_MODEL_ID), None)
        if _enabled(fb):
            return fb
        for x in models:
            if _enabled(x):
                return x
        return None

    def get_model_for_task(self, task: str) -> Optional[Dict[str, Any]]:
        """
        返回指定任务专用模型（如 'memory'、'summarize'、'chat'）。
        在模型配置里用 for_<task>: true 标记。
        hidden=true 的模型仍可用于内部任务；enabled=false 的模型不可用。
        若找不到，回退到当前活跃模型。
        """
        self.config = self._load_config()
        flag = f"for_{task}"
        if task == "chat":
            active = self.get_active_model()
            if active and active.get("for_chat"):
                return active
        for model in self.config.get("models", []):
            if (model.get(flag)
                    and model.get("enabled") is not False
                    and model.get("api_key", "")):
                return model
        return self.get_active_model()

    def get_model_for_capability(
        self,
        capability: str,
        *,
        preferred_task: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Return an enabled, configured model that explicitly declares a capability.

        Unlike ``get_model_for_task``, this method never falls back to an incapable
        active model.  Internal multimodal callers use it so changing the main chat
        model cannot silently route an image request to a text-only endpoint.
        """
        self.config = self._load_config()
        capability_flag = (
            capability if capability.startswith("supports_") else f"supports_{capability}"
        )
        candidates = [
            model
            for model in self.config.get("models", [])
            if model.get("enabled") is not False
            and bool(model.get("api_key"))
            and bool(model.get(capability_flag))
        ]
        if not candidates:
            return None
        if preferred_task:
            preferred_flag = f"for_{preferred_task}"
            preferred = next((model for model in candidates if model.get(preferred_flag)), None)
            if preferred is not None:
                return preferred
        active_id = str(self.config.get("active_model") or "").strip()
        active = next((model for model in candidates if model.get("id") == active_id), None)
        return active or candidates[0]

    def set_active_model(self, model_id: str):
        """切换活跃模型。enabled=false 的模型不允许被激活。"""
        target = next((m for m in self.config.get("models", []) if m["id"] == model_id), None)
        if target is None:
            return False
        if target.get("enabled") is False:
            logger.warning(f"⚠️ [模型管理] 尝试激活已禁用模型 {model_id}，已拒绝")
            return False
        self.config["active_model"] = model_id
        if self._legacy_single_file:
            self._save_config()
        else:
            self._save_manifest_only()
        return True

    def add_model(self, model_data: Dict[str, Any]) -> str:
        # 若无 id 则生成
        if "id" not in model_data:
            import uuid
            model_data["id"] = f"custom-{str(uuid.uuid4())[:8]}"
        
        # 检查重复
        if any(m["id"] == model_data["id"] for m in self.config.get("models", [])):
            raise ValueError(f"Model with ID {model_data['id']} already exists")

        if not self._legacy_single_file:
            self._ensure_custom_fragment_for_new_model(model_data["id"])
            
        self.config.setdefault("models", []).append(model_data)
        self._save_config()
        return model_data["id"]

    def update_model(self, model_id: str, updates: Dict[str, Any]) -> bool:
        for model in self.config.get("models", []):
            if model["id"] == model_id:
                model.update(updates)
                self._save_config()
                return True
        return False

    def delete_model(self, model_id: str) -> bool:
        models = self.config.get("models", [])
        initial_len = len(models)
        models = [m for m in models if m["id"] != model_id]
        
        if len(models) < initial_len:
            self.config["models"] = models
            
            # 若活跃模型被删除，优先 DeepSeek 视觉，否则选第一个仍可用模型
            if self.config.get("active_model") == model_id and models:
                prefer = next(
                    (x for x in models if x.get("id") == DEFAULT_FALLBACK_MODEL_ID and x.get("enabled") is not False),
                    None,
                )
                if prefer:
                    self.config["active_model"] = prefer["id"]
                else:
                    nxt = next((x for x in models if x.get("enabled") is not False), models[0])
                    self.config["active_model"] = nxt.get("id", "")
            elif not models:
                self.config["active_model"] = ""
                
            self._save_config()
            return True
        return False

    @staticmethod
    def _format_exception_chain(exc: Exception) -> str:
        """格式化异常链，输出更可读的错误上下文。"""
        parts = []
        current = exc
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            parts.append(f"{type(current).__name__}: {current!r}")
            current = current.__cause__ or current.__context__
        return " <- ".join(parts)

    @staticmethod
    def _is_qwen_model(base_url: str, target_model: str) -> bool:
        ident = f"{base_url or ''} {target_model or ''}".lower()
        return "dashscope.aliyuncs.com" in ident or "qwen" in ident

    @staticmethod
    def _build_qwen_responses_url(endpoint: str) -> str:
        base = str(endpoint or "").rstrip("/")
        if not base:
            return ""
        if base.endswith("/responses"):
            return base
        if "/api/v2/apps/protocols/compatible-mode/v1" in base:
            return base.replace("/chat/completions", "").rstrip("/") + "/responses"
        if "/compatible-mode/v1" in base:
            host = base.split("/compatible-mode/v1", 1)[0]
            return host + "/api/v2/apps/protocols/compatible-mode/v1/responses"
        return base.replace("/chat/completions", "").rstrip("/") + "/responses"

    async def _test_connection_impl(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """测试模型连接性（结构化返回，供普通/详细模式复用）。"""
        import httpx

        provider = str(config.get("provider") or config.get("type") or "openai").lower()
        api_key = str(config.get("api_key") or "")
        base_url = str(config.get("base_url") or config.get("endpoint") or "")
        model_name = str(config.get("model_name") or config.get("model_id") or config.get("id") or "")
        target_model = model_name or config.get("model_name") or config.get("id")

        try:
            from .config import httpx_client
            client = httpx_client
            use_shared = client is not None

            if not use_shared:
                client = httpx.AsyncClient(timeout=10.0)

            try:
                if provider == "openai" or provider.startswith("openai"):
                    if not base_url:
                        return {"success": False, "message": "Base URL 不能为空"}
                    if not target_model:
                        return {"success": False, "message": "模型标识符 (Model Name) 不能为空"}

                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    is_qwen = self._is_qwen_model(base_url, target_model)
                    if is_qwen:
                        url = self._build_qwen_responses_url(base_url)
                        data = {
                            "model": target_model,
                            "input": [{"role": "user", "content": "hi"}],
                            "stream": False,
                        }
                        # 测试探活显式关闭思考，避免深度思考模型在短超时下被误判为不可用。
                        if "enable_thinking" in config:
                            data["enable_thinking"] = False
                        timeout_sec = 25.0
                    else:
                        url = f"{base_url.rstrip('/')}/chat/completions"
                        is_xai = "api.x.ai" in base_url
                        data = {
                            "model": target_model,
                            "messages": [{"role": "user", "content": "hi"}],
                        }
                        if is_xai:
                            data["max_completion_tokens"] = 16384
                            timeout_sec = 45.0
                        else:
                            data["max_tokens"] = 16384
                            timeout_sec = 10.0

                    logger.info(f"📤 发送测试请求到: {url}, 模型: {target_model}")
                    await save_chat_debug_log(None, None, "model_test", target_model or "", data, "REQUEST")
                    response = await client.post(url, headers=headers, json=data, timeout=timeout_sec)

                elif provider == "gemini":
                    return {"success": False, "message": "Gemini 测试接口待完善，但通常配置正确即可使用。"}
                else:
                    return {"success": False, "message": f"不支持的 Provider 类型: {provider}"}

                if response.status_code == 200:
                    await save_chat_debug_log(None, None, "model_test", target_model or "", response.json(), "RESPONSE")
                    return {
                        "success": True,
                        "message": "连接成功",
                        "status_code": response.status_code,
                    }

                try:
                    err_msg = response.json().get("error", {}).get("message", response.text)
                except Exception:
                    err_msg = response.text
                await save_chat_debug_log(None, None, "model_test", target_model or "", err_msg, f"ERROR_{response.status_code}")
                return {
                    "success": False,
                    "message": f"HTTP {response.status_code}: {err_msg}",
                    "status_code": response.status_code,
                }
            finally:
                if not use_shared:
                    await client.aclose()
        except Exception as e:
            chain = self._format_exception_chain(e)
            logger.error(f"❌ 模型连接测试失败: {chain}")
            logger.debug("模型连接测试堆栈:\n%s", traceback.format_exc())
            return {
                "success": False,
                "message": f"网络请求失败: {chain}",
                "error_chain": chain,
            }

    async def test_connection(self, config: Dict[str, Any]) -> tuple:
        """测试模型连接性 (异步) - 兼容旧返回格式 (success, message)。"""
        result = await self._test_connection_impl(config)
        return result.get("success", False), result.get("message", "未知错误")

    async def test_connection_detailed(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """测试模型连接性并返回详细结构化结果。"""
        return await self._test_connection_impl(config)

model_manager = ModelManager()
