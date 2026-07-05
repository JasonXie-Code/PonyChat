# -*- coding: utf-8 -*-
"""Use the configured DeepSeek flash model to structure one MLP database entry.

Example:
    python structure_entry_with_llm.py --name 紫悦
    python structure_entry_with_llm.py --name 暮光闪闪 --out twilight_profile.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from structure_entry_cleaning import (
    clean_generated_value,
    configure_episode_manifest,
    norm_key,
    sanitize_generation_sections,
)


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mlp_world.db"
MANUAL_ALIASES_FILE = BASE_DIR / "manual_aliases.json"
EPISODE_MANIFEST_FILE = BASE_DIR / "episode_manifest.json"
configure_episode_manifest(EPISODE_MANIFEST_FILE)
REPO_ROOT = Path(__file__).resolve().parents[3]
MLP_DATA_DIR = REPO_ROOT / "Backend" / "data" / "mlp"
REFINED_DIR = MLP_DATA_DIR / "refined"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))



def load_manual_aliases() -> dict[str, str]:
    if not MANUAL_ALIASES_FILE.exists():
        return {}
    try:
        data = json.loads(MANUAL_ALIASES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        norm_key(k): str(v).strip()
        for k, v in data.items()
        if str(k).strip() and not str(k).startswith("_") and str(v).strip()
    }


def clean_aliases(values: list[str]) -> list[str]:
    aliases: list[str] = []
    for raw in values:
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not value or len(value) > 42:
            continue
        if value.upper() == "EG":
            continue
        if any(x in value for x in ("参阅", "对于", "人类形态", "列表", "第4季", "第5季", "彩虹摇滚")):
            continue
        if value not in aliases:
            aliases.append(value)
    return aliases


def resolve_entry(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    target = load_manual_aliases().get(norm_key(name), name.strip())
    row = conn.execute(
        """
        SELECT *
          FROM entries
         WHERE canonical_name=? OR title=?
         ORDER BY CASE entity_type
                  WHEN 'character' THEN 1
                  WHEN 'location' THEN 2
                  WHEN 'concept' THEN 3
                  ELSE 9 END
         LIMIT 1
        """,
        (target, target),
    ).fetchone()
    if row:
        return row

    alias_row = conn.execute(
        """
        SELECT e.*
          FROM entity_aliases a
          JOIN entries e ON e.id=a.entry_id
         WHERE a.alias_norm=?
         ORDER BY CASE e.entity_type
                  WHEN 'character' THEN 1
                  WHEN 'location' THEN 2
                  WHEN 'concept' THEN 3
                  ELSE 9 END
         LIMIT 1
        """,
        (norm_key(name),),
    ).fetchone()
    return alias_row


def clip_context(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
    if last > limit // 2:
        return cut[: last + 1]
    return cut.rstrip() + "..."


def related_tokens(entry: sqlite3.Row, aliases: list[str]) -> list[str]:
    values = [entry["canonical_name"], entry["title"], *aliases]
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or len(text) > 40:
            continue
        if text.upper() == "EG" or "人类形态" in text or "参阅" in text:
            continue
        out.append(text)
    return list(dict.fromkeys(out))


def fetch_related_entries(
    conn: sqlite3.Connection,
    entry: sqlite3.Row,
    aliases: list[str],
    *,
    limit: int = 14,
) -> list[dict[str, Any]]:
    tokens = related_tokens(entry, aliases)
    rows = conn.execute(
        """
        SELECT id, canonical_name, title, entity_type, importance, summary, content, source_filename
          FROM entries
         WHERE id != ?
           AND entity_type IN ('episode','song','concept','location','item','species')
        """,
        (entry["id"],),
    ).fetchall()
    scored: list[tuple[int, dict[str, Any]]] = []
    type_weight = {"episode": 35, "location": 30, "item": 28, "concept": 24, "song": 18, "species": 12}
    for row in rows:
        hay = f"{row['canonical_name']} {row['title']} {row['summary']} {row['content']}"
        score = type_weight.get(row["entity_type"], 0)
        for token in tokens:
            if not token:
                continue
            count = hay.count(token)
            if count:
                score += min(80, count * 12)
            if token in str(row["canonical_name"] or "") or token in str(row["title"] or ""):
                score += 80
        if score <= type_weight.get(row["entity_type"], 0):
            continue
        scored.append(
            (
                score,
                {
                    "canonical_name": row["canonical_name"],
                    "title": row["title"],
                    "entity_type": row["entity_type"],
                    "importance": row["importance"],
                    "source_filename": row["source_filename"],
                    "summary": clip_context(row["summary"], 700),
                    "content_excerpt": clip_context(row["content"], 1200),
                    "score": score,
                },
            )
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _score, item in scored[:limit]]


def fetch_related_refined_episodes(
    entry: sqlite3.Row,
    aliases: list[str],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not REFINED_DIR.exists() or not EPISODE_MANIFEST_FILE.exists():
        return []
    try:
        manifest = json.loads(EPISODE_MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    tokens = related_tokens(entry, aliases)
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in manifest:
        if not isinstance(item, dict):
            continue
        season = int(item.get("season") or 0)
        if season not in (1, 2, 3):
            continue
        candidates = [
            REFINED_DIR / f"{item.get('en_title', '')}.txt",
            REFINED_DIR / f"{item.get('cn_title', '')}.txt",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        hay = text
        score = 0
        for token in tokens:
            if not token:
                continue
            count = hay.count(token)
            if count:
                score += min(120, count * 18)
        title_joined = f"{item.get('cn_title','')} {item.get('en_title','')}"
        if any(token and token in title_joined for token in tokens):
            score += 120
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "code": item.get("code"),
                    "cn_title": item.get("cn_title"),
                    "en_title": item.get("en_title"),
                    "source_filename": path.name,
                    "refined_excerpt": clip_context(text, 2600),
                    "score": score,
                },
            )
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _score, item in scored[:limit]]


def fetch_entry_context(conn: sqlite3.Connection, name: str, *, max_content_chars: int) -> dict[str, Any]:
    entry = resolve_entry(conn, name)
    if not entry:
        raise SystemExit(f"未找到条目：{name}")

    aliases = [
        r["alias"]
        for r in conn.execute(
            "SELECT alias FROM entity_aliases WHERE entry_id=? ORDER BY length(alias), alias LIMIT 120",
            (entry["id"],),
        ).fetchall()
    ]
    facts = [
        {
            "fact_text": r["fact_text"],
            "season_scope": json.loads(r["season_scope_json"] or "[]"),
            "source_filename": r["source_filename"],
        }
        for r in conn.execute(
            "SELECT fact_text, season_scope_json, source_filename FROM facts WHERE entry_id=? ORDER BY id LIMIT 80",
            (entry["id"],),
        ).fetchall()
    ]
    public_aliases = clean_aliases(aliases)

    return {
        "entry": {
            "id": entry["id"],
            "canonical_name": entry["canonical_name"],
            "title": entry["title"],
            "entity_type": entry["entity_type"],
            "importance": entry["importance"],
            "season_scope": json.loads(entry["season_scope_json"] or "[]"),
            "source_filename": entry["source_filename"],
            "source_kind": entry["source_kind"],
            "content_hash": entry["content_hash"],
        },
        "aliases": public_aliases,
        "summary": entry["summary"],
        "facts": facts,
        "content": str(entry["content"] or "")[:max_content_chars],
        "related_entries": fetch_related_entries(conn, entry, public_aliases),
        "related_refined_episodes": fetch_related_refined_episodes(entry, public_aliases),
    }


def load_deepseek_flash_config() -> dict[str, Any]:
    try:
        from Backend.model_manager import load_merged_model_config
    except Exception:
        from backend.model_manager import load_merged_model_config  # type: ignore

    cfg = load_merged_model_config()
    for model in cfg.get("models", []):
        if model.get("id") == "deepseek-v4-flash" or model.get("model_name") == "deepseek-v4-flash":
            if not model.get("api_key"):
                raise SystemExit("deepseek-v4-flash 配置缺少 api_key")
            return dict(model)
    raise SystemExit("未找到 deepseek-v4-flash 配置")


SYSTEM_PROMPT = """你是 PonyChat 的小马世界资料库结构化编辑器。
任务：把单个《我的小马驹：友谊就是魔法》条目整理成可供聊天回复调用的 JSON。

硬性范围：
- 只允许使用 G4 动画正剧第 1-3 季信息。
- 不允许使用官方小说、漫画、电影、特别篇、小马国女孩、人类形态、非官方设定、S4 及以后内容。
- 只根据用户提供的条目信息整理；信息不足时填 null 或空数组，不要编造。
- 每个非 null 字段都必须能从输入条目的 aliases、summary、facts、content、related_entries 或 related_refined_episodes 中找到直接依据。
- 不要用你对角色的外部常识补全字段；即使内容属于 S1-S3，只要输入里没有明说，也不要写。
- 输出结果中绝对不要出现剧集名、季集编号、季数、集数、source_filename、season_scope、season_codes、S1/S2/S3、S1E01 这类数值或字段；所有事件只用世界内概括表达。
- 主要角色名必须统一为：紫悦、珍奇、碧琪、苹果嘉儿、柔柔、云宝、宇宙公主、月亮公主、穗龙。不要输出暮光闪闪、瑞瑞、萍琪派、苹果杰克、小蝶、云宝黛茜、塞拉斯蒂娅、露娜、斯派克等旧名作为主要显示名。
- abilities 只能写输入直接描述的能力、魔法表现或身份能力；不要补充未在输入出现的法术。
- character_profile 必须服务于角色资料与背景信息，不要写“扮演提示”“回复建议”“语气提示”之类字段。
- 尽量避免重复：外貌只写在 appearance，性格只写在 personality，喜好只写在 preferences_and_interests，行为习惯只写在 behavior_and_habits；summary 只做概括，不复述所有字段。
- 外貌字段要细分毛色/体色、鬃毛颜色、尾巴颜色、瞳色、可爱标记、配饰、其他视觉特征；没有依据就填 null 或空数组。
- 性格字段要尽量从剧情证据中提取：核心特质、情绪模式、优点、缺点、动机、害怕/不安、价值观。
- 喜好字段要提取喜欢的活动、食物/甜点、兴趣、常去地点、重视的事物；没有依据就留空。
- 行为习惯字段要提取派对习惯、搞笑方式、唱歌/音乐、社交方式、解决问题方式、反复出现的举动。
- 不要用“名字（关系）”“名字（种类）”“能力：说明”这种混合字符串承载结构信息；关系、种类、能力说明必须拆成 name/relation/species_or_type/description/category 等字段。
- character_brief 是网页查询和分步生成查询都会直接携带的短字段块，必须包含 species、gender、mbti、personality_brief、interests_brief。
- personality_brief 和 interests_brief 必须各自控制在 20 个中文字符以内。
- mbti/16人格不是剧中明示设定时，必须标记 inferred=true 和 confidence=medium/low，不要当成 canon 事实。
- reply_material 只能是 simple_query.summary 的更口语、更短改写，不能加入 summary/fields 中没有的新信息。
- not_in_scope_removed 只记录输入中确实出现且已被删除的非范围内容；不要把仍保留的亲属、身份或事件写进去。
- simple_query.summary、reply_material、reply_usage.*.material 必须是语法通顺的中文，不要出现“后在天角兽”这类残缺表达。
- confidence 用 high/medium/low/missing；无法从输入确认的字段必须是 missing 或 null/[]。
- reply_usage.background 用于“只作为背景信息”；reply_usage.important_basis 用于“本回合重要回复依据”。
- type_specific_profile 只填写当前条目类型对应的 profile，其它类型填 null。
- character_development 只用于角色条目，记录角色从早期到 S3 的身份、能力、关系、地位或剧情作用变化。
- character_development 只能写输入中直接出现的变化；可以使用 related_entries / related_refined_episodes 中的相关事件摘要作为依据；如果输入没有成长线索，填 null 或空数组。
- 对角色条目，要优先抽取对聊天有背景价值的信息：情绪触发点、不安来源、常见行为、兴趣偏好、关系互动、能力限制、做事方式，以及从事件中学到的改变。
- 对角色条目，如果 related_entries / related_refined_episodes 中出现“学到、意识到、最终、接受、相信、道歉、和好、选择、承认、改变、成长”等线索，必须整理进 character_development；这不是扮演提示，而是角色背景事实。
- 不要把制作人员评论或设定来源写进角色资料；如果这类文字只说明了角色性格，请只保留剧中可用的性格结论。
- detailed_query、character_profile、generation_material、reply_usage 都不能保留剧集标题、季集编号、剧集 source 或任何剧集字段。
- step_generation_material 与 reply_usage 是给分步生成/角色主回复使用的素材，必须使用世界内表达；禁止出现剧集名、集数、S1/S2/S3、S3E13、第一季/第二季/第三季、“这一集”“剧集”等出戏标记。
- 如果需要表达角色发展，只说“后来”“最终”“经历某次重要事件后”等世界内说法，不要说具体剧集标题或编号。
- 删除配音演员、制作人员、商品、导航、维基维护、未来家庭等非剧中事实；不要在输出里解释删了什么。

输出要求：
- 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
- 中文字段值优先；英文名、英文别名可保留。
- simple_query.summary 控制在 100 个中文字符以内。
- detailed_query.summary 控制在 500 个中文字符以内。
"""


def character_schema_v3() -> dict[str, Any]:
    return {
        "schema_version": "mlp_entry_profile_v3",
        "entry_type": "character|location|concept|episode|song|item|species|other",
        "canonical_name": "规范中文名",
        "common": {
            "names": {
                "zh": None,
                "en": None,
                "full_name": None,
                "aliases": [],
                "nicknames": [],
                "translation_variants": [],
            },
            "importance": None,
        },
        "query_views": {
            "simple": {
                "budget_chars": 100,
                "summary": "只概括身份、最核心性格或用途，不重复外貌细节",
                "key_fields": [],
            },
            "detailed": {
                "budget_chars": 500,
                "sections": {
                    "identity": None,
                    "personality": None,
                    "preferences": None,
                    "behavior": None,
                    "relationships": None,
                    "development": None,
                },
            },
        },
        "character_brief": {
            "species": None,
            "gender": None,
            "mbti": {
                "type": None,
                "name_zh": None,
                "inferred": True,
                "confidence": "medium|low|missing",
                "note": "16人格为根据角色行为和性格短评推断，非剧中明示设定",
            },
            "personality_brief": "20字以内性格短语",
            "interests_brief": "20字以内兴趣短语",
        },
        "character_profile": {
            "identity": {
                "gender": None,
                "species": None,
                "age_stage": None,
                "residence": None,
                "workplace": None,
                "occupations_or_roles": [],
                "element_or_symbol": None,
                "community_role": [],
                "pet_or_companion": [],
            },
            "appearance": {
                "body": {"coat_or_body_color": None, "body_shape_or_build": None, "notable_body_traits": []},
                "hair": {"mane_color": None, "mane_style": None, "tail_color": None, "tail_style": None},
                "eyes": {"eye_color": None, "eye_shape_or_expression": None},
                "cutie_mark": {"description": None, "meaning": None},
                "magic_or_aura": {"color": None, "notes": []},
                "accessories_or_clothing": [],
                "other_visual_traits": [],
            },
            "personality": {
                "core_traits": [],
                "emotional_patterns": [],
                "strengths": [],
                "flaws_or_limits": [],
                "insecurities_or_fears": [],
                "motivations": [],
                "values": [],
            },
            "preferences_and_interests": {
                "likes": [],
                "dislikes": [],
                "favorite_foods_or_sweets": [],
                "hobbies": [],
                "favorite_activities": [],
                "important_places": [],
                "things_she_cares_about": [],
            },
            "behavior_and_habits": {
                "party_habits": [],
                "humor_style": [],
                "song_or_music_habits": [],
                "social_style": [],
                "problem_solving_style": [],
                "recurring_actions": [],
                "stress_or_conflict_behavior": [],
            },
            "abilities_and_tools": {
                "special_abilities": [],
                "practical_skills": [],
                "signature_tools": [],
                "pets_or_companions": [],
                "limits_or_costs": [],
            },
            "relationships": {
                "family": [],
                "close_friends": [],
                "mentors_or_teachers": [],
                "work_or_household": [],
                "pets": [],
                "other": [],
            },
            "character_development": {
                "arc_summary": "一句话概括角色在允许范围内的阶段性成长；没有永久身份变化也可以写事件中学到的改变",
                "starting_point": "早期呈现的状态、习惯或局限",
                "ending_point_s3": "到第三季范围内呈现的状态；没有明确结尾就写较后的状态",
                "turning_points": [
                    "发生了什么变化，用世界内说法描述，不必写剧集编号"
                ],
                "lessons_or_realizations": [
                    "角色明确学到、承认、接受或意识到的事"
                ],
                "ability_growth": [
                    "能力被朋友理解、被自己更好使用、限制被呈现等"
                ],
                "relationship_growth": [
                    "和朋友之间信任、沟通、道歉、和好、支持的变化"
                ],
                "status_changes": [
                    "身份、地位、住处、工作、象征身份的变化；没有就留空"
                ],
                "development_notes": [
                    "对角色背景有用但不适合放入上面字段的成长记录"
                ],
            },
        },
        "confidence": {
            "overall": "high|medium|low",
            "field_confidence": {
                "identity": "high|medium|low|missing",
                "appearance": "high|medium|low|missing",
                "personality": "high|medium|low|missing",
                "preferences_and_interests": "high|medium|low|missing",
                "behavior_and_habits": "high|medium|low|missing",
                "abilities_and_tools": "high|medium|low|missing",
                "relationships": "high|medium|low|missing",
                "character_development": "high|medium|low|missing",
            },
            "missing_fields": [],
            "risk_notes": [],
        },
            "step_generation_material": {
                "ooc_safe": True,
                "simple": {
                    "budget_chars": 100,
                    "facts": {"identity": [], "personality": [], "background": []},
                "text": "给分步生成用的世界内背景素材，不含外部标题、编号、季数",
            },
            "detailed": {
                "budget_chars": 500,
                    "facts": {
                        "identity": [],
                        "personality": [],
                        "preferences": [],
                        "behavior": [],
                        "abilities": [
                            {
                                "name": "能力、技能或工具名",
                                "category": "special_ability|practical_skill|tool|other",
                                "description": None,
                            }
                        ],
                        "relationships": {
                            "family": [{"name": "角色名", "relation": "父亲/母亲/姐妹等"}],
                            "friends": [{"name": "角色名", "relation": "朋友"}],
                            "household": [{"name": "角色名或群体名", "relation": "同住/同事/照顾者等"}],
                            "pets": [{"name": "名字", "relation": "宠物", "species_or_type": "种类"}],
                        },
                        "development": [],
                        "appearance": [],
                    },
                    "text": "给分步生成用的重要事实素材，不含外部标题、编号、季数",
                },
            "forbidden_terms_removed": [],
        },
        "disambiguation": {
            "primary_entity": "规范名",
            "matched_aliases": [],
            "avoid_confusion_with": [],
            "ambiguity_notes": [],
        },
        "search_profile": {
            "match_keywords": [],
            "language_variants": {"zh_cn": [], "zh_tw": [], "en": [], "nicknames": []},
            "importance": None,
        },
    }


def build_user_prompt(context: dict[str, Any]) -> str:
    schema = character_schema_v3()
    return (
        "请把【输入条目】整理成【目标 JSON Schema】。\n\n"
        "【目标 JSON Schema】\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n\n【输入条目】\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise
        return json.loads(match.group(0))



async def structure_with_deepseek(context: dict[str, Any]) -> dict[str, Any]:
    from Backend.providers import call_llm
    from Backend.reasoning_policy import resolve_reasoning_policy

    model_cfg = load_deepseek_flash_config()
    model_name = str(model_cfg.get("model_name") or model_cfg.get("id") or "deepseek-v4-flash")
    endpoint = str(model_cfg.get("endpoint") or "")
    no_thinking_cfg = dict(model_cfg)
    no_thinking_cfg["enable_thinking"] = False
    policy = resolve_reasoning_policy(
        model_name,
        "classify",
        active_model=no_thinking_cfg,
        endpoint=endpoint,
    )
    response = await call_llm(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(context)},
        ],
        model_cfg,
        task="classify",
        temperature=0.1,
        max_tokens=4096,
        json_mode=True,
        timeout=90,
        reasoning_policy=policy,
    )
    return sanitize_generation_sections(clean_generated_value(extract_json_object(response.text)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="紫悦", help="Entry name or alias, e.g. 紫悦")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--out", default="", help="Optional JSON output file")
    parser.add_argument("--max-content-chars", type=int, default=12000)
    parser.add_argument("--print-context", action="store_true", help="Print the LLM input context without calling API")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        context = fetch_entry_context(conn, args.name, max_content_chars=max(2000, args.max_content_chars))
    finally:
        conn.close()

    if args.print_context:
        print(json.dumps(context, ensure_ascii=False, indent=2))
        return

    result = asyncio.run(structure_with_deepseek(context))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
