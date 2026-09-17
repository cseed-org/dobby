import asyncio
from unittest.mock import patch

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from starlette.requests import Request

from test_login import database
from dashboard import local_admin
from dashboard.auth import get_current_user
from dashboard.database import get_db
from dashboard.login_config import is_local_request, require_provider
from dashboard.models import Session, User
from dashboard.passwords import hash_password, verify_password
from dashboard.routers import auth


def test_password_hashing():
    password = 'a-long-local-password'
    first = hash_password(password)
    assert first != hash_password(password)
    assert password not in first
    assert verify_password(password, first)
    assert not verify_password('incorrect-password', first)
    assert not verify_password(password, 'invalid')
    with pytest.raises(ValueError):
        hash_password('short')


@pytest.mark.parametrize('host, allowed', [
    ('192.168.1.50', True), ('10.0.0.5', True), ('172.16.0.5', True),
    ('127.0.0.1', True), ('::1', True), ('fd00::1', True),
    ('::ffff:192.168.1.50', True), ('8.8.8.8', False),
    ('172.32.0.1', False), ('0.0.0.0', False), ('testclient', False),
])
def test_local_networks(host, allowed):
    request = Request({'type': 'http', 'client': (host, 1234), 'headers': []})
    assert is_local_request(request) is allowed


@pytest.mark.parametrize('mode, provider, allowed', [
    ('oauth', 'google', True), ('oauth', 'discord', True), ('oauth', 'local', False),
    ('local', 'google', False), ('local', 'discord', False), ('local', 'local', True),
    ('both', 'google', True), ('both', 'local', True),
])
def test_modes(mode, provider, allowed, monkeypatch):
    monkeypatch.setenv('AUTH_MODE', mode)
    request = Request({'type': 'http', 'client': ('192.168.1.50', 1234), 'headers': []})
    if allowed:
        require_provider(provider, request)
    else:
        with pytest.raises(HTTPException) as error:
            require_provider(provider, request)
        assert error.value.status_code == 404


def test_local_login_session_logout_and_reset(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'both')
    auth._attempts.clear()

    async def run():
        engine, sessions = await database()
        app = FastAPI()
        app.include_router(auth.router, prefix='/auth')

        async def db_override():
            async with sessions() as db:
                yield db
        app.dependency_overrides[get_db] = db_override

        @app.get('/me')
        async def me(user=Depends(get_current_user)):
            return {'role': user.role}

        try:
            with patch.object(local_admin, 'SessionLocal', sessions):
                await local_admin.save_admin('leona', hash_password('a-long-local-password'))
            transport = httpx.ASGITransport(app=app, client=('192.168.1.50', 1234))
            async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
                credentials = {'username': ' Leona ', 'password': 'a-long-local-password'}
                assert (await client.get('/auth/methods')).json() == {'local': True, 'oauth': True}
                assert (await client.get('/me')).status_code == 401
                assert (await client.post('/auth/local', json=credentials,
                    headers={'Origin': 'http://evil.example'})).status_code == 403
                response = await client.post('/auth/local', json=credentials)
                assert response.status_code == 200
                assert 'HttpOnly' in response.headers['set-cookie']
                assert (await client.get('/me')).json() == {'role': 'admin'}
                monkeypatch.setenv('AUTH_MODE', 'oauth')
                assert (await client.get('/me')).status_code == 404
                assert (await client.post('/auth/local', json=credentials)).status_code == 404
                monkeypatch.setenv('AUTH_MODE', 'both')
                assert (await client.post('/auth/logout')).status_code == 204
                assert (await client.get('/me')).status_code == 401
                assert (await client.post('/auth/local', json=credentials)).status_code == 200
                with patch.object(local_admin, 'SessionLocal', sessions):
                    await local_admin.save_admin('leona', hash_password('changed-local-password'))
                assert (await client.get('/me')).status_code == 401
                assert (await client.post('/auth/local', json=credentials)).status_code == 401
                credentials['password'] = 'changed-local-password'
                assert (await client.post('/auth/local', json=credentials)).status_code == 200
                assert (await client.post('/auth/local', json=credentials)).status_code == 200
                assert (await client.post('/auth/local', json=credentials)).status_code == 429
            public = httpx.ASGITransport(app=app, client=('8.8.8.8', 1234))
            async with httpx.AsyncClient(transport=public, base_url='http://test') as client:
                assert (await client.post('/auth/local', json=credentials)).status_code == 403
            async with sessions() as db:
                assert len((await db.execute(select(User))).scalars().all()) == 1
                assert all(s.provider == 'local' for s in (await db.execute(select(Session))).scalars())
        finally:
            await engine.dispose()
    asyncio.run(run())
