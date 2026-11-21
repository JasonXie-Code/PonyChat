import asyncio
from fastapi import HTTPException
from Backend.chat_modules.chat_error_event import chat_error_event


def test_mobile_decoder_receives_timeout_cause_and_http_status():
    import json
    try:
        try:
            raise TimeoutError('模型生成超过60秒')
        except TimeoutError as cause:
            raise HTTPException(502, detail='本次模型回复超时，消息已保留') from cause
    except HTTPException as exc:
        event = chat_error_event(exc, job_id='job-1', conversation_id='conv-1', client_id='single')
    decoded = json.loads(event['message'])
    assert decoded['message'] == '本次回复未能完成，请重试。'
    assert 'HTTP 502' in decoded['debug_detail']
    assert 'TimeoutError: 模型生成超过60秒' in decoded['debug_detail']
    assert '请求ID: job-1' in decoded['debug_detail']


def test_secret_redaction_and_non_mobile_message_compatibility():
    event = chat_error_event(RuntimeError('Authorization: Bearer abc-secret api_key=xyz sk-private'), client_id='web')
    assert event['message'] == '本次回复未能完成，请重试。'
    assert 'abc-secret' not in event['debug_detail']
    assert 'xyz' not in event['debug_detail']
    assert 'sk-private' not in event['debug_detail']


def test_empty_cancellation_has_a_useful_type():
    event = chat_error_event(asyncio.CancelledError())
    assert 'CancelledError' in event['debug_detail']
    assert '异常未提供详细原因' in event['debug_detail']
