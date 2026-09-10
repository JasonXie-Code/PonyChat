"""Shared importance rubric for memory writing and evidence-based rescoring."""

IMPORTANCE_POLICY = """记忆重要性评分：每次stage_memory必须明确提交importance，取1至10的整数，不能省略或统一填5。
按这条事实对今后交流的长期价值评分，与certainty（事实是否确定）分开判断：
1至2：一次性闲聊、低价值琐事，通常不保存；用户明确要求保存时可以低分保存。
3至4：短期、局部且后续用途较少的事件或信息。
5至6：有具体内容的普通经历、共同活动、一般约定。
7至8：稳定偏好、持续生活背景、反复有用的需求或重要经历。
9至10：证据明确的重大关系节点、长期承诺、重要边界及对后续交流有重大影响的事项。表白、确认关系、长期承诺、重大和解或信任变化按实际意义评估，不能凭某个词直接打高分。
日、周、月、年摘要沿用原分层基准6、7、8、10；摘要层级分数不用于把正文中的每个细节都升级为重大事实。
用户说“记住”、文本很长、情绪强烈或亲密程度高，都不能单独成为高分依据。无原文支持的推测不能当成重要事实。
更新已有记忆时明确重新评估importance；事实意义未变时保留原分数，不能因为工具省略参数而重置成5。
评分是内部元数据，不向用户口头汇报评分过程。"""

IMPORTANCE_SCHEMA = {'type': 'integer', 'minimum': 1, 'maximum': 10,
                     'description': '必填，按长期价值逐条评分：1-2琐事、3-4短期信息、5-6普通经历、7-8稳定重要需求、9-10重大节点。不得统一填5。'}


def require_importance(arguments):
    value = arguments.get('importance')
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError('importance is required and must be an integer from 1 to 10; assess this memory explicitly')
    return value
