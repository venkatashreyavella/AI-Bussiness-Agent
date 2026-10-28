"""Exercise the running application's complete review workflow using fictional data."""
import os
import httpx
from dotenv import load_dotenv


def run():
    load_dotenv()
    with httpx.Client(base_url=os.getenv('API_BASE_URL', 'http://127.0.0.1:8000'),
                      headers={'Authorization': 'Bearer ' + os.environ['APP_API_TOKEN']}, timeout=240) as client:
        health = client.get('/health')
        health.raise_for_status()
        if health.json()['provider'] != 'demo':
            raise RuntimeError('Smoke test uses fictional data and requires LLM_PROVIDER=demo')
        payload = dict(sender='accounts@aisha.example', subject='Fictional deployment smoke check',
                       body='Please confirm invoice INV-1042 for Aisha Trading LLC. Our copy says AED 3500.')
        response = client.post('/emails', json=payload)
        response.raise_for_status()
        ident = response.json()['id']
        assert client.post('/emails', json=payload).json()['id'] == ident
        response = client.post(f'/emails/{ident}/process')
        response.raise_for_status()
        result = response.json()
        assert result['extraction']['invoice_number'] == 'INV-1042'
        assert 'Pending' in result['draft']['body'] and '3500.00' in result['draft']['body']
        assert any(t['name'] == 'get_invoice_status' and t['outcome']['found'] for t in result['tools'])
        draft = result['draft']
        response = client.post(f"/drafts/{draft['id']}/approve", json={'revision': draft['revision'], 'reviewer': 'Fictional smoke test'})
        response.raise_for_status()
        assert response.json()['status'] == 'approved' and not response.json()['sending_enabled']
        draft = response.json()
        response = client.patch(f"/drafts/{draft['id']}", json={'revision': draft['revision'], 'body': draft['body']})
        response.raise_for_status()
        assert response.json()['status'] == 'pending' and response.json()['reviewed_at'] is None
        assert client.post(f"/drafts/{draft['id']}/send").status_code == 409
        assert client.get(f'/emails/{ident}/results').json()['email']['status'] == 'processed'
        assert client.get('/analytics').json()['total_emails'] >= 1
    print('PASS: authenticated submission, deduplication, extraction, database lookup, grounded draft, approval, approval reset, disabled sending and persisted analytics.')


if __name__ == '__main__':
    run()
