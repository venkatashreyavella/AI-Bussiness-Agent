"""Verify the initial owner account against the running API without printing credentials."""
import os
import httpx
from dotenv import load_dotenv


def run():
    load_dotenv()
    url = os.getenv('API_BASE_URL', 'http://127.0.0.1:8000')
    username = os.getenv('BOOTSTRAP_ADMIN_USERNAME', 'owner')
    password = os.environ['DASHBOARD_PASSWORD']
    with httpx.Client(base_url=url, timeout=30) as client:
        response = client.post('/auth/login', json={'username': username, 'password': password})
        response.raise_for_status()
        token = response.json()['access_token']
        auth = {'Authorization': 'Bearer ' + token}
        user = client.get('/auth/me', headers=auth)
        assert user.status_code == 200 and user.json()['role'] == 'admin'
        assert 'password_hash' not in user.text
        assert client.get('/users', headers=auth).status_code == 200
        assert client.get('/emails', headers=auth).status_code == 200
        assert client.get('/users/audit/events', headers=auth).status_code == 200
        assert client.get('/emails', headers={'Authorization': 'Bearer ' + password}).status_code == 401
        assert client.get('/users', headers={'Authorization': 'Bearer ' + os.environ['APP_API_TOKEN']}).status_code == 403
        assert client.post('/auth/logout', headers=auth).status_code == 204
        assert client.get('/auth/me', headers=auth).status_code == 401
    print('PASS: individual owner login, database session, account management, private credential boundary, shared-password rejection and session revocation.')


if __name__ == '__main__':
    run()
