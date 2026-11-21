Run three independent PonyChat normal-chat reply tests.

Important:
- Do not use normal_chat_turn, because it is a deterministic local mock.
- For each test, call get_character_profile for the requested character, call update_working_state, and use search_memory_fragments/read_summaries only when supplied.
- Then you, Goose, must write the final character reply according to the returned character profile and persona.
- Output compact JSON only. Do not include tool traces, hidden reasoning, markdown fences, or explanations.

Return this JSON shape:
{
  "model": "deepseek-v4-flash",
  "tests": [
    {
      "case": "...",
      "character_id": "...",
      "character_name": "...",
      "raw_user_input": "...",
      "goose_reply": "..."
    }
  ]
}

Tests:
1. character_id=trixie
   raw_user_input=今天有点累，陪我聊会儿
   recent messages=[{"role":"user","content":"今天有点累，陪我聊会儿"}]
   memory_fragments=[]
   summaries={}

2. character_id=muffins
   raw_user_input=你现在在做什么？我想听你随便说点日常。
   recent messages=[{"role":"user","content":"你现在在做什么？我想听你随便说点日常。"}]
   memory_fragments=["用户喜欢被轻松自然地接话，不喜欢客服式长篇建议。"]
   summaries={"week":"这一周用户多次提到想要更像朋友之间自然聊天。"}

3. character_id=aloe
   raw_user_input=帮我把我们刚刚这几句整理成一个简短文档。
   recent messages=[
     {"role":"user","content":"今天有点累，陪我聊会儿"},
     {"role":"assistant","content":"那先把肩膀放下来一点，慢慢说。"},
     {"role":"user","content":"帮我把我们刚刚这几句整理成一个简短文档。"}
   ]
   memory_fragments=[]
   summaries={}
