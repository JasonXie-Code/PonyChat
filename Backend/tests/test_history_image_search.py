"""History retains ordinary image references even after transfer bytes expire."""
import asyncio
import sqlite3

from test_normal_delivery_pacing import delivery_db, ui_routes


def test_paged_and_search_preserve_legacy_and_attachment_images(monkeypatch, delivery_db):
    routes, _ = ui_routes(monkeypatch, delivery_db)
    from Backend.db.message_attachments import attachment_row_to_dict

    image = attachment_row_to_dict(('att', 'conv', 'ordinary', 'image', None, None,
        '/chat_images/tmp_received.png', '旅行图片', 64, 64,
        '{"source":"web_search","sha256":"abc"}', '2026-09-12'))

    async def attachments(_conn, conversation, mids):
        return {'ordinary': [image]} if conversation == 'conv' and 'ordinary' in mids else {}
    monkeypatch.setattr(routes, 'load_attachments_for_messages', attachments)
    with sqlite3.connect(delivery_db) as conn:
        conn.executemany('INSERT INTO messages(conversation_id,message_id,content,image_url,sequence_number) '
            'VALUES(?,?,?,?,?)', [('conv', 'ordinary', '', None, 1),
                                 ('conv', 'legacy', '旅行', '/chat_images/old.png', 2),
                                 ('conv', 'inline', '旅行 ![](/chat_images/inline.png)', '/chat_images/inline.png', 3)])
        conn.execute('INSERT INTO message_attachments(conversation_id,message_id,name) VALUES(?,?,?)',
                     ('conv', 'ordinary', '旅行图片'))
    async def case():
        args = dict(username='pacing-test', character_id='main', x_chat_auth='synthetic')
        pages = [await routes.get_conversation_messages_paged(conversation_id='conv', **args),
                 await routes.search_messages(query='旅行', **args)]
        for page in pages:
            rows = {r['message_id']: r for r in page.get('messages', page.get('results', []))}
            assert rows['ordinary']['attachments'][0] == image
            assert rows['legacy']['attachments'] == [{'type': 'image', 'url': '/chat_images/old.png', 'name': '图片'}]
            assert not rows['inline'].get('attachments')
        assert routes._history_image_attachments('', image['url'], [image]) == [image]
    asyncio.run(case())
