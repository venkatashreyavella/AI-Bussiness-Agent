"""Load the fixed fictional evaluation emails through the authenticated application API."""
import json
import os
from pathlib import Path
import httpx
from dotenv import load_dotenv

if __name__ == '__main__':
    load_dotenv()
    with httpx.Client(base_url=os.getenv('API_BASE_URL', 'http://127.0.0.1:8000'),
                      headers={'Authorization': 'Bearer ' + os.environ['APP_API_TOKEN']}, timeout=30) as client:
        count = 0
        for line in Path('evaluation/dataset.jsonl').read_text(encoding='utf-8').splitlines():
            response = client.post('/emails', json=json.loads(line)['email'])
            response.raise_for_status()
            count += 1
    print(f'Loaded {count} fictional emails (duplicates reused). Open the dashboard to process them.')
