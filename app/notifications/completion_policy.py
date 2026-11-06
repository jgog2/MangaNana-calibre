"""A bell means every requested output was verified in the library."""
def successful_batch(ledger):
    if not isinstance(ledger, dict):
        return False
    rows = ledger.get('outputs') or ()
    counts = ledger.get('counts') or {}
    if (not rows or ledger.get('requested') != len(rows) or
            any(ledger.get(key) for key in ('unexpected', 'generation_failures', 'accounting_error')) or
            any(counts.get(key) for key in ('skipped', 'conflicted', 'failed', 'cancelled'))):
        return False
    return all(isinstance(row,dict) and row.get('status') in ('imported', 'updated') and
               isinstance(row.get('verified'),dict) and
               bool((row.get('verified') or {}).get('book_id')) for row in rows)
