"""一次性脚本：删除 character.py 中的 JAILBREAK_PROMPT 定义及注入逻辑"""
import re

path = r"p:\PonyChat\Backend\chat_modules\character.py"
with open(path, encoding="utf-8") as f:
    src = f.read()

# 1. 删除整个 JAILBREAK_PROMPT 常量（三引号字符串 + 末尾换行）
src = re.sub(
    r'JAILBREAK_PROMPT = """.*?"""\n\n',
    '',
    src,
    flags=re.DOTALL
)

# 2. 简化 load_character_prompts：移除 jailbreak_allowed 参数及相关逻辑
# 原函数签名
src = src.replace(
    "def load_character_prompts(username: str, char_id: str, jailbreak_allowed: bool = False) -> tuple[str, str]:",
    "def load_character_prompts(username: str, char_id: str, **_kw) -> tuple[str, str]:"
)

# 原拦截 + 注入块（lines 82-93）
old_block = (
    "        char_jailbreak_flag = char.get(\"jailbreak\", False)\n"
    "        if char_jailbreak_flag and not jailbreak_allowed:\n"
    "            logger.warning(\n"
    "                f\"🚫 [破限拦截] 角色 {char.get('name', char_id)} 设置了破限，\"\n"
    "                f\"但账号 {username} 无权限（非 developer/admin），已强制关闭\"\n"
    "            )\n"
    "        has_jailbreak = char_jailbreak_flag and jailbreak_allowed\n"
    "\n"
    "        persona_parts = []\n"
    "        if has_jailbreak:\n"
    "            persona_parts.append(JAILBREAK_PROMPT)\n"
    "            logger.info(f\"🔓 [Jailbreak] 为角色 {char.get('name', char_id)} 注入了深度破限指令\")\n"
    "        if sys_prompt:\n"
)
new_block = (
    "\n"
    "        persona_parts = []\n"
    "        if sys_prompt:\n"
)
src = src.replace(old_block, new_block)

# 3. 简化 load_character_system_prompt 签名
src = src.replace(
    "def load_character_system_prompt(username: str, char_id: str, jailbreak_allowed: bool = False) -> str:\n"
    "    persona, instr = load_character_prompts(username, char_id, jailbreak_allowed=jailbreak_allowed)",
    "def load_character_system_prompt(username: str, char_id: str, **_kw) -> str:\n"
    "    persona, instr = load_character_prompts(username, char_id)"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print("character.py patched OK")
