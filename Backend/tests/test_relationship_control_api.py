import asyncio

import httpx
from fastapi import FastAPI

from test_autonomous_upgrade_integration import database


def test_control_api_roundtrip_validation_and_verified_owner(database, monkeypatch):
    from Backend.routes import relationship, auth
    from Backend import relationship_insights
    monkeypatch.setattr(relationship, 'get_database', lambda: database)
    monkeypatch.setattr(relationship_insights, 'get_database', lambda: database)
    async def verify(token):
        return {'alice-token': 'alice', 'bob-token': 'bob'}.get(token)
    monkeypatch.setattr(auth, 'auth_token_verify', verify)
    app = FastAPI()
    app.include_router(relationship.router)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            body = {'username': 'alice', 'character_id': 'twilight',
                    'relationship_mode': 'manual', 'relationship_stage': 'committed_partner'}
            url = '/api/relationship/state'
            assert (await client.post(url, json=body)).status_code == 401
            assert (await client.post(url, json=body, headers={'X-Chat-Auth': 'bob-token'})).status_code == 403
            client.headers['X-Chat-Auth'] = 'alice-token'
            saved = await client.post(url, json=body)
            assert saved.status_code == 200, saved.text
            assert saved.json()['relationship_mode'] == 'manual'
            assert saved.json()['relationship_stage'] == 'committed_partner'
            loaded = await client.get(url, params={'username': 'alice', 'character_id': 'twilight'})
            assert loaded.json()['manual_relationship_stage'] == 'committed_partner'
            invalid = await client.post(url, json={**body, 'relationship_stage': 'invalid'})
            assert invalid.status_code == 400
            assert (await client.post(url, json={**body, 'relationship_mode': 'invalid'})).status_code == 422
            reset = await client.post(url, json={k: v for k, v in
                {**body, 'relationship_mode': 'auto'}.items() if k != 'relationship_stage'})
            assert reset.status_code == 200
            assert reset.json()['relationship_mode'] == 'auto'
            assert reset.json()['manual_relationship_stage'] is None
    asyncio.run(scenario())
