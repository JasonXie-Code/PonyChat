"""Normal-chat prompt composition for the existing Agent, preserving its guards.

Call run_skill_turn(actual_turn, **kwargs) at the request boundary. Each call owns
its catalog, profile and loaded modules; nothing is shared between users/turns.
The production service uses this entry; the lower-level turn keeps its guards.
"""
from __future__ import annotations
from .Prompts import (AUTONOMOUS_PROMPT_SKILLS_TEXT, CHAT_SKILL_TEXTS,
                     COGNITION_CORE, evidence, narrative, SKILL_WHEN, SKILL_TITLES)

import hashlib
import json
import re
import time
from copy import deepcopy

from .harness_runtime import HarnessTool
from .prompt_surface_rules import dash_allowed
from .autonomous_direct import direct_system, expression_manual
from . import interaction_modes
from .autonomous_prompt_rules import (
    character_body, reply_language, followup, followup_summary, speech,
)





def character_card(home_profile):
    """Only creator-authored homepage fields stay resident; no outline heuristics."""
    return home_profile.strip() or AUTONOMOUS_PROMPT_SKILLS_TEXT['character_card_1']


def search_profile(profile, query, offset=None):
    """Rank exact source windows by multiple terms, retaining evidence offsets."""
    if offset is not None and (offset != 0 or not query):
        start = min(max(0, int(offset)), len(profile))
        end = min(len(profile), start + 4000)
        return {"mode": "page", "text": profile[start:end], "start": start,
                "next_offset": end if end < len(profile) else None}
    terms = list(dict.fromkeys(re.findall(r"[\w]+", query.lower())))[:16]
    if not terms:
        raise ValueError("Search requires at least one word keyword")
    hits = []
    lowered = profile.lower()
    for term in terms:
        for match in list(re.finditer(re.escape(term), lowered))[:80]:
            start = max(0, profile.rfind("\n", 0, max(0, match.start() - 220)) + 1)
            start = max(start, match.start() - 420)
            end = min(len(profile), match.end() + 500)
            newline = profile.find("\n", end)
            if 0 <= newline < end + 200:
                end = newline
            excerpt = lowered[start:end]
            score = sum(1 for t in terms if t in excerpt)
            hits.append((score, start, end))
    spans = []
    for score, start, end in sorted(hits, key=lambda h: (-h[0], h[1])):
        if any(start < other_end and end > other_start for other_start, other_end in spans):
            continue
        spans.append((start, end))
        if len(spans) == 4:
            break
    matched_terms = [term for term in terms if term in lowered]
    snippets = [{"start": a, "end": b, "text": profile[a:b]} for a, b in spans]
    return {"mode": "search", "query_terms": terms, "matched_terms": matched_terms,
            "unmatched_terms": [t for t in terms if t not in matched_terms], "matched": bool(snippets), "snippets": snippets,
            "text": "\n\n".join(item["text"] for item in snippets),
            "next_offset": None if snippets else 0,
            "hint": AUTONOMOUS_PROMPT_SKILLS_TEXT['search_profile_1']}


class PromptSkills:
    def __init__(self, *, profile, preferences, business, normal_module, home_profile="",
                 reference_guidance="", preference_guidance="",
                 user_background=None):
        from .autonomous_scene_facts import participant_context
        self.participants = participant_context(user_background)
        self.profile = profile
        self.tool_call_limit = normal_module.NORMAL_TOOL_CALL_LIMIT
        self.card = character_card(home_profile)
        self.has_intro = bool(re.search(r"(?m)^简介：[ \t]*\S", home_profile))
        self.reference_searched = False
        self.reference_evidence = []
        self.reference_queries = set()
        self.keyword_retry_required = False
        self.gate_rejections = 0
        self.allow_dash = False
        self.current_text = ""
        self.preferences = preferences
        self.reference_guidance = reference_guidance
        self.preference_guidance = preference_guidance
        self.business = business
        self.loaded = set()
        self.interaction_mode = None
        self.reads = []
        self.attempts = []
        self.input_channel = None
        self.task_snapshot = {}
        self.catalog = {
            "evidence": (SKILL_WHEN["evidence"], evidence),
            "character_body": (SKILL_WHEN["character_body"], character_body + "\n" + reference_guidance),
            "relationship": (SKILL_WHEN["relationship"], CHAT_SKILL_TEXTS['relationship']),
            "delivery": (SKILL_WHEN["delivery"], CHAT_SKILL_TEXTS['delivery']),
            "web_search": (SKILL_WHEN["web_search"], CHAT_SKILL_TEXTS['web_search']),
            "mlp_reference": (SKILL_WHEN["mlp_reference"], CHAT_SKILL_TEXTS['mlp_reference']),
            "memory": (SKILL_WHEN["memory"], CHAT_SKILL_TEXTS['memory']),
            "media_expression": (SKILL_WHEN["media_expression"], CHAT_SKILL_TEXTS['media_expression']),
            "media_handling": (SKILL_WHEN["media_handling"], CHAT_SKILL_TEXTS['media_handling']),
            "media_response": (SKILL_WHEN["media_response"], CHAT_SKILL_TEXTS['media_response']),
            "narrative": (SKILL_WHEN["narrative"], narrative),
            "schedule": (SKILL_WHEN["schedule"], getattr(self.business, "schedule_guidance", "")),
            "lifecycle": (SKILL_WHEN["lifecycle"], getattr(self.business, "lifecycle_guidance", "")),
            "handoff": (SKILL_WHEN["handoff"], getattr(self.business, "handoff_guidance", "")),
        }
        # 偏好块只拼一次：调用方给的 guidance 与已保存值指向同一段文本时，
        # 不再在"当前已保存偏好："后面重复一遍。
        preferences_body = CHAT_SKILL_TEXTS['preferences']
        if preference_guidance:
            preferences_body += "\n" + preference_guidance
        if self.preferences and self.preferences.strip() != (preference_guidance or "").strip():
            preferences_body += '\n当前已保存偏好：\n' + self.preferences
        self.catalog["preferences"] = (SKILL_WHEN["preferences"], preferences_body)
        from .autonomous_behavior_policy import continuity
        self.catalog["continuity"] = (SKILL_WHEN["continuity"], continuity)
        self.catalog["speech"] = (SKILL_WHEN["speech"], speech)
        self.catalog["followup"] = (SKILL_WHEN["followup"], followup)
        self.catalog.update(interaction_modes.CATALOG)
        self.catalog['reply_expression'] = (SKILL_WHEN['reply_expression'], expression_manual())
        self.catalog['reply_language'] = (SKILL_WHEN['reply_language'], reply_language)
        self.catalog['voice_reply'] = (SKILL_WHEN['voice_reply'], CHAT_SKILL_TEXTS['voice_reply'])

    def prepare_task_manuals(self, data):
        """Keep live contracts discoverable, without repeating their full manuals."""
        if data.get('followup_contract'):
            data['followup_contract'] = followup_summary
        if data.get('description_shortcut_contract'):
            manual = data['description_shortcut_contract']
            if manual != 'load_chat_skill:shortcut':
                if self.catalog.get('shortcut', ('', None))[1] != manual:
                    self.loaded.discard('shortcut')
                self.catalog['shortcut'] = (SKILL_WHEN['shortcut'], manual)
            data['description_shortcut_contract'] = 'load_chat_skill:shortcut'
        elif 'description_shortcut_contract' in data:
            self.catalog.pop('shortcut', None)
            self.loaded.discard('shortcut')
        data['available_skills'] = [{'name': name, 'when': pair[0]} for name, pair in self.catalog.items()]

    def bind_live_input(self, channel):
        if channel is None or channel is self.input_channel:
            return
        self.input_channel = channel
        prepare = channel.prepare_input

        async def compact_update(rows):
            blocks = await prepare(rows)
            blocks = deepcopy(blocks)
            for block in blocks:
                if block.get('type') == 'text':
                    data = json.loads(block['text'])
                    self.prepare_task_manuals(data)
                    self.task_snapshot.update(deepcopy(data))
                    block['text'] = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
                    break
            return blocks
        channel.prepare_input = compact_update

    async def load(self, args):
        """Read one or more skill manuals in a single round trip.

        Fixed manuals are re-read every turn, so the single-name form made the
        Agent spend one model round trip per manual before it could start
        answering. `names` lets it read the whole fixed set at once; the
        single-name form and its result shape are unchanged.
        """
        batch = args.get("names")
        if batch is None:
            requested = [args["name"]] if args.get("name") else []
        else:
            requested = list(batch) if isinstance(batch, list) else []
        names = list(dict.fromkeys(str(name) for name in requested))
        if not names:
            raise ValueError("Provide a skill name or a names list")
        if len(names) > len(self.catalog):
            raise ValueError("Too many chat skills requested at once")
        loaded = []
        for name in names:
            if name not in self.catalog:
                raise ValueError("Unknown chat skill")
            if name in interaction_modes.MODES:
                self.loaded.difference_update(interaction_modes.MODES)
                self.interaction_mode = name
            self.loaded.add(name)
            self.reads.append({"type": "skill", "name": name})
            loaded.append({"skill": name, "instructions": self.skill_instructions(name),
                           "scope": "current_turn_only"})
        if len(loaded) == 1 and batch is None:
            return loaded[0]
        return {"skills": loaded}

    def skill_instructions(self, name):
        """Use the registered name as the main title, retaining all body text."""
        title = SKILL_TITLES[name]
        body = self.catalog[name][1]
        return body if body.startswith(title + '\n') else title + '\n' + body

    async def reference(self, args):
        query = str(args.get("query") or "").strip()
        if not query and "offset" not in args:
            raise ValueError("Provide query keywords or an explicit page offset")
        result = search_profile(self.profile, query, args.get("offset"))
        if result["mode"] == "search":
            self.reference_searched = True
            self.reference_queries.add(tuple(sorted(result["query_terms"])))
            self.keyword_retry_required = len(self.reference_queries) == 1 and len(result["matched_terms"]) < min(2, len(result["query_terms"]))
        result["keyword_retry_required"] = self.keyword_retry_required
        if self.keyword_retry_required:
            result["next_action"] = AUTONOMOUS_PROMPT_SKILLS_TEXT['result_next_action_1']
        self.reference_evidence.append(result)
        self.reference_evidence = self.reference_evidence[-4:]
        self.reads.append({"type": "character_reference", "query": query, "offset": args.get("offset"),
                           "query_terms": result.get("query_terms", []),
                           "matched_terms": result.get("matched_terms", []),
                           "unmatched_terms": result.get("unmatched_terms", []),
                           "keyword_retry_required": self.keyword_retry_required,
                           "matched": result.get("matched"), "source_spans":
                           [{"start": x["start"], "end": x["end"]} for x in result.get("snippets", [])]})
        return {**result, "total_characters": len(self.profile),
                "note": AUTONOMOUS_PROMPT_SKILLS_TEXT['reference_1']}

    def transform(self, prompt, system, *, allow_tools=True):
        blocks = deepcopy(prompt) if isinstance(prompt, list) else None
        if blocks is not None:
            index = next(i for i, b in enumerate(blocks) if b.get("type") == "text")
            data = json.loads(blocks[index]["text"])
        else:
            data = json.loads(prompt)
        batch = data.get("current_user_batch") or [data.get("latest_user_message") or {}]
        if not isinstance(batch, list):
            batch = [batch]
        self.current_text = "\n".join(str(m.get("content", "")) if isinstance(m, dict) else str(m) for m in batch)
        self.allow_dash = dash_allowed(data, self.preferences)
        data["character_profile"] = self.card
        data["participants"] = deepcopy(self.participants)
        if self.reference_evidence:
            data["character_reference_evidence"] = deepcopy(self.reference_evidence)
        environment = str(data.get("environment") or "")
        if self.preferences:
            environment = environment.replace(self.preferences, "")
        if self.preference_guidance:
            environment = environment.replace(self.preference_guidance, "")
        data["environment"] = environment.strip()
        self.prepare_task_manuals(data)
        # Keep available calendar summaries intact; compact only explicit missing placeholders.
        calendar = data.get("calendar_memory")
        if isinstance(calendar, dict):
            for kind in ("daily", "weekly", "monthly", "annual"):
                if isinstance(calendar.get(kind), list):
                    entries = calendar[kind]
                    calendar[kind] = [e for e in entries if e.get("status") != "missing"]
                    calendar[kind + "_missing_periods"] = [e.get("period") for e in entries if e.get("status") == "missing"]
        # The tool returns manuals in this session. Never inject them again into
        # system on retries; this keeps the task prompt stable and avoids copies.
        new_system = direct_system(COGNITION_CORE)
        required_skills = ['evidence', 'reply_expression', 'reply_language', 'voice_reply', 'delivery']
        # State-dependent rules are read as skills, never appended to system.
        scene_fields = (data.get('current_scene') or {}).get('fields') or {}
        if any(key.startswith('item:') and isinstance(item, dict) and item.get('value')
               for key, item in scene_fields.items()):
            required_skills.append('continuity')
        data['interaction_context'] = {'previous_mode': interaction_modes.previous_mode(data),
                                       'selected_this_turn': self.interaction_mode}
        if data.get('web_images_available'):
            self.catalog['image_style'] = (SKILL_WHEN['image_style'], CHAT_SKILL_TEXTS['image_style'])
            data['available_skills'].append({'name': 'image_style', 'when': self.catalog['image_style'][0]})
            # The catalog exposes image-style selection to the Agent.
        if data.get('current_scene') is not None:
            required_skills.append('continuity')
        if data.get('followup_contract'):
            required_skills.append('followup')
        if data.get('description_shortcut_contract'):
            required_skills.append('shortcut')
            required_skills.extend(('character_body', 'continuity'))
        required_skills = list(dict.fromkeys(required_skills))
        # Invariant: one copy of each manual per prompt. A manual already handed
        # over in finalization_skills is never repeated in verified_observations,
        # and a skill the Agent read twice is still injected once.
        injected: set[str] = set()
        if not allow_tools:
            # Finalization can exhaust tools before every manual was read. Supply
            # the missing skill documents as explicit context, not system rules.
            finalization = [
                {'skill': name, 'instructions': self.skill_instructions(name)}
                for name in required_skills if name not in self.loaded]
            injected.update(item['skill'] for item in finalization)
            data['finalization_skills'] = finalization
        if self.loaded:
            data["loaded_skills"] = sorted(self.loaded)
            if data.get("previous_attempt"):
                observations = data.setdefault("verified_observations", [])
                carried = {item["result"]["skill"] for item in observations
                           if item.get('tool') == 'load_chat_skill'
                           and isinstance(item.get('result'), dict)}
                pending = [
                    {"tool": "load_chat_skill",
                     "result": {"skill": name, "instructions": self.skill_instructions(name)}}
                    for name in sorted(self.loaded)
                    if name not in injected and name not in carried]
                observations.extend(pending)
        data['required_skills_before_reply'] = [name for name in required_skills if name not in self.loaded]
        pending = list(data.get("required_tools_before_reply") or [])
        if allow_tools and (self.interaction_mode is None or data['required_skills_before_reply']):
            pending.append('load_chat_skill')
            new_system += AUTONOMOUS_PROMPT_SKILLS_TEXT['transform_1']
        if allow_tools and (not self.reference_searched or self.keyword_retry_required):
            pending.append("read_character_reference")
        data["required_tools_before_reply"] = pending
        data["character_reference_policy"] = {"has_homepage_intro": self.has_intro,
            "searched_this_turn": self.reference_searched,
            "rule": AUTONOMOUS_PROMPT_SKILLS_TEXT['data_character_reference_policy_1']}
        if pending:
            new_system += AUTONOMOUS_PROMPT_SKILLS_TEXT['transform_4'] + ", ".join(pending) + AUTONOMOUS_PROMPT_SKILLS_TEXT['transform_3']
        if data.get("completion_feedback"):
            new_system += AUTONOMOUS_PROMPT_SKILLS_TEXT['transform_2']
        data["visible_punctuation_policy"] = {"dash_allowed": self.allow_dash}
        for meta in (data.get("source_message_times") or {}).values():
            if isinstance(meta, dict):
                meta.pop("meaning", None)
        from .autonomous_wire_format import compact_task_data
        compact_task_data(data)
        # Finish with the actual conversation and current request. Background
        # projections/tool catalogs must not displace the newest user turn.
        # Reorder only: preserve every source message and batch boundary.
        for key in ("recent_raw_messages", "current_user_batch", "latest_user_message"):
            if key in data:
                data[key] = data.pop(key)
        self.task_snapshot = deepcopy(data)
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if blocks is not None:
            blocks[index]["text"] = encoded
        self.attempts.append({"before_system_characters": len(system), "after_system_characters": len(new_system),
                              "interaction_previous_mode": interaction_modes.previous_mode(data),
                              "before_input_characters": len(json.dumps(prompt, ensure_ascii=False)),
                              "after_input_characters": len(json.dumps(blocks or encoded, ensure_ascii=False)),
                              "loaded_skills": sorted(self.loaded)})
        return blocks if blocks is not None else encoded, new_system

    def runner(self, base_runner):
        async def call(prompt, config, tools, **options):
            force_no_tools = bool(options.pop('force_no_tools', False))
            delivery_only = bool(options.get('delivery_only'))
            prompt, options["system_prompt"] = self.transform(
                prompt, options["system_prompt"], allow_tools=not force_no_tools and not delivery_only)
            channel = options.get('input_channel')
            self.bind_live_input(channel)
            if channel is not None:
                from .harness_live_input import LIVE_INPUT_RULE
                options['system_prompt'] += '\n' + LIVE_INPUT_RULE
            extra = {
                "load_chat_skill": HarnessTool(self.load, AUTONOMOUS_PROMPT_SKILLS_TEXT['extra_1'], {
                    "type": "object", "properties": {
                        "name": {"type": "string"},
                        "names": {"type": "array", "items": {"type": "string"}, "maxItems": 24}},
                    "additionalProperties": False}),
                "read_character_reference": HarnessTool(self.reference, AUTONOMOUS_PROMPT_SKILLS_TEXT['extra_2'], {
                    "type": "object", "properties": {"query": {"type": "string", "maxLength": 100},
                    "offset": {"type": "integer", "minimum": 0}}, "additionalProperties": False}),
            }
            if delivery_only:
                tools = {k: v for k, v in tools.items() if k in options.get('delivery_tool_names', ())}
                extra = {}
                options['system_prompt'] += AUTONOMOUS_PROMPT_SKILLS_TEXT['call_1']
            if options.get('max_tool_calls') == 0 and not force_no_tools and not delivery_only and (
                    self.interaction_mode is None or not self.reference_searched or self.keyword_retry_required):
                # Reference requirements are added by this prompt adapter;
                # the outer format-repair loop cannot see them yet.
                options['max_tool_calls'] = self.tool_call_limit
            if options.get('max_tool_calls') == 0:
                tools, extra = {}, {}
                options['system_prompt'] += AUTONOMOUS_PROMPT_SKILLS_TEXT['call_2']
            tools = dict(tools)
            if 'stage_memory' in tools:
                original = tools['stage_memory']

                async def scoped_memory(arguments):
                    if self.interaction_mode is None:
                        raise ValueError(AUTONOMOUS_PROMPT_SKILLS_TEXT['scoped_memory_1'])
                    return await original.callback(interaction_modes.scope_memory(arguments, self.interaction_mode))

                tools['stage_memory'] = HarnessTool(scoped_memory, original.description, original.parameters)
            result = await base_runner(prompt, config, {**tools, **extra}, **options)
            if result.get('finish_reason') == 'completed' and self.interaction_mode is None:
                result['mode_selection_required'] = True
            return result
        return call


async def run_skill_turn(actual_turn, *, home_profile="", reference_guidance="",
                         preference_guidance="", user_background=None, **kwargs):
    from . import autonomous_normal as normal
    from .harness_runtime import run_harness_turn
    from .autonomous_expression_paths import serial_session_class
    session_class = serial_session_class(PromptSkills, HarnessTool)
    session = session_class(profile=kwargs["character_profile"], preferences=kwargs.get("personal_preferences", ""),
                           business=kwargs.get("business_tools"), normal_module=normal, home_profile=home_profile,
                           reference_guidance=reference_guidance, preference_guidance=preference_guidance,
                           user_background=user_background)
    args = dict(kwargs)
    args["harness_runner"] = session.runner(kwargs.get("harness_runner") or run_harness_turn)
    result = await actual_turn(**args)
    expression_review = {'status': 'disabled', 'executor': 'main_agent',
                         'independent_review_calls': 0}
    interaction_modes.attach_mode(result, session.interaction_mode)
    result["prompt_skills"] = {"version": "agent-scoped-skills-v3-cursor", "expression_read_policy": "first_pass_no_repair", "expression_paths": list(session.selected_paths), "expression_gate_events": session.gate_events, "reply_composer": "agent", "expression_review": expression_review, "dash_allowed": session.allow_dash, "has_homepage_intro": session.has_intro, "searched_this_turn": session.reference_searched, "gate_rejections": session.gate_rejections, "attempts": session.attempts, "reads": session.reads,
                               "interaction_mode": session.interaction_mode,
                               "deduplication_read_stats": {
                                   "count": len(session.deduplication_reads),
                                   "rereads": max(0, len(session.deduplication_reads) - 1),
                                   "reasons": list(session.deduplication_reads)},
                               "profile_before": len(session.profile), "profile_after": len(session.card),
                               "profile_sha256": hashlib.sha256(session.profile.encode()).hexdigest()}
    return result
