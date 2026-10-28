from collections import Counter
import re


def prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return dict(precision=precision, recall=recall, f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                tp=tp, fp=fp, fn=fn)


def suspected_unsupported_claims(body, evidence):
    """Conservative screening, not a semantic truth oracle. Human review remains required."""
    records = [r for item in evidence for r in item.get('records', [])]
    flags = []
    if re.search(r'\b(paid|settled|received your payment)\b', body, re.I) and not any(r.get('status', '').lower() == 'paid' for r in records):
        flags.append('possible_unsupported_payment_claim')
    known_numbers = {str(r.get(k)) for r in records for k in ('invoice_number', 'order_number') if r.get(k)}
    for number in re.findall(r'\b(?:INV|ORD)-\d+\b', body, re.I):
        if number.upper() not in known_numbers:
            flags.append('unverified_reference:' + number)
    for currency, amount in re.findall(r'\b(AED|USD|EUR|GBP)\s*([\d,]+(?:\.\d+)?)', body):
        if not any(r.get('currency') == currency and float(r.get('amount', -1)) == float(amount.replace(',', '')) for r in records):
            flags.append('unverified_amount')
    for value in re.findall(r'\b\d{4}-\d{2}-\d{2}\b', body):
        if not any(r.get('due_date') == value for r in records):
            flags.append('unverified_date')
    return flags


def score(cases):
    labels = sorted({c['expected']['category'] for c in cases})
    categories = {}
    for label in labels:
        categories[label] = prf(sum(c.get('actual', {}).get('category') == label and c['expected']['category'] == label for c in cases),
                               sum(c.get('actual', {}).get('category') == label and c['expected']['category'] != label for c in cases),
                               sum(c.get('actual', {}).get('category') != label and c['expected']['category'] == label for c in cases))
    fields = {}
    for field in ['sender', 'customer_name', 'invoice_number', 'order_number', 'amount', 'currency', 'due_date', 'urgency']:
        tp = fp = fn = 0
        for case in cases:
            actual, expected = case.get('actual', {}).get(field), case['expected'].get(field)
            if actual is not None and actual == expected:
                tp += 1
            else:
                fp += actual is not None
                fn += expected is not None
        fields[field] = prf(tp, fp, fn)
    n = len(cases)
    lookups = [value for c in cases for value in
               (c.get('lookup_correct', []) + [False] * max(0, len(c.get('lookups', {})) - len(c.get('lookup_correct', []))))]
    return dict(samples=n, classification_accuracy=sum(c.get('actual', {}).get('category') == c['expected']['category'] for c in cases) / n,
                per_category=categories, extraction_fields=fields,
                required_field_completeness=sum(c.get('complete', False) for c in cases) / n,
                structured_validation_success_rate=sum(c.get('validated', False) for c in cases) / n,
                successful_processing_rate=sum(c.get('success', False) for c in cases) / n,
                api_failure_rate=sum(c.get('api_failure', False) for c in cases) / n,
                lookup_correctness=sum(lookups) / len(lookups) if lookups else None,
                lookup_checks=len(lookups),
                drafts_flagged_by_factual_screen=sum(bool(c.get('claim_flags')) for c in cases),
                unsupported_claim_semantic_rate=None,
                limitations=['Factual screening checks payment claims, identifiers, amounts and dates only; semantic claim correctness is unmeasured.',
                             'Required completeness measures presence of core output fields and correct reporting of missing identifiers.',
                             'Fictional labels are authored test expectations, not representative of production inboxes.'])
