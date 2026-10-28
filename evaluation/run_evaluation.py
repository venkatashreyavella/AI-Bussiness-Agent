import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from openai import APIError
from app.core.config import get_settings
from app.db.session import Base, make_engine
from app.schemas import Extraction
from app.services.llm_service import get_provider, DemoProvider
from app.services.email_service import extract_email_data, retrieve_business_context, generate_reply_draft
from app.services.business_tools import BusinessTools
from app.services.evaluation_service import score, suspected_unsupported_claims
from scripts.seed_database import seed


def run(live=False, output=Path('evaluation/reports')):
    settings = get_settings()
    if live and settings.llm_provider != 'openai':
        raise ValueError('--live requires LLM_PROVIDER=openai, OPENAI_API_KEY and OPENAI_MODEL')
    provider = get_provider(settings) if live else DemoProvider()
    # Isolated fixture database: evaluation never changes the inbox or business records.
    engine = make_engine('sqlite://')
    Base.metadata.create_all(engine)
    cases = [json.loads(line) for line in Path('evaluation/dataset.jsonl').read_text(encoding='utf-8').splitlines() if line]
    with Session(engine) as db:
        seed(db)
        for case in cases:
            try:
                extraction = extract_email_data(provider, case['email'])
                case['actual'], case['validated'] = extraction.model_dump(mode='json'), True
                case['complete'] = all([extraction.summary, extraction.requested_action, extraction.suggested_next_step]) and set(case['expected_missing']).issubset(extraction.missing_information)
                tools = BusinessTools(db)
                retrieve_business_context(extraction, tools)
                draft = generate_reply_draft(provider, case['email'], extraction, tools)
                case['draft'] = draft.body
                case['evidence'] = tools.evidence
                case['claim_flags'] = suspected_unsupported_claims(draft.body, tools.evidence)
                case['lookup_correct'] = []
                for number, expected_found in case['lookups'].items():
                    tool = 'get_invoice_status' if number.startswith('INV-') else 'get_order_status'
                    relevant = [e for e in tools.evidence if e['tool'] == tool]
                    case['lookup_correct'].append(bool(relevant) and all(e['status'] == 'success' and e['found'] == expected_found for e in relevant))
                case['success'] = True
            except Exception as exc:
                case['success'], case['api_failure'] = False, isinstance(exc, APIError)
                case['error_type'] = type(exc).__name__
    report = dict(provider='openai' if live else 'demo_rules', model=settings.openai_model if live else None,
                  timestamp=datetime.now(timezone.utc).isoformat(), metrics=score(cases))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'latest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (output / 'cases.jsonl').write_text('\n'.join(json.dumps(c) for c in cases), encoding='utf-8')
    (output / 'report.md').write_text('# Business Inbox evaluation\n\nProvider: ' + report['provider'] +
        '\n\nThese scores measure the selected provider on 60 fictional cases. Offline scores are not LLM accuracy claims.\n\n```json\n' +
        json.dumps(report['metrics'], indent=2) + '\n```\n\nReview cases.jsonl for individual drafts, evidence and failures. Semantic unsupported claims require manual review.\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Use configured OpenAI model (incurs API charges)')
    args = parser.parse_args()
    run(args.live)
