"""Record observed URLs, then reconcile against the published library; never infer the platform total."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sync_library import source_key, active


def reconcile(library, urls=(), account=None, end_evidence=None):
    library = Path(library).resolve()
    lock = library/'.sync-lock'
    lock.mkdir()
    try:
        version = active(library)
        if version is None:
            raise ValueError('Initialize the library with sync_library.py first')
        path = library/'collection-inventory.json'
        data = json.loads(path.read_text()) if path.exists() else {'account': account, 'items': {}, 'end_evidence': None}
        if data['account'] and account and data['account'] != account:
            raise ValueError('Account mismatch; do not combine different accounts')
        data['account'] = data['account'] or account
        now = datetime.now(timezone.utc).isoformat()
        for url in urls:
            key = source_key(url)
            data['items'].setdefault(key, {'url': url, 'first_seen': now})
        posts = json.loads((version/'library.json').read_text())['posts']
        indexed = {source_key(p['url']): p for p in posts}
        for key,p in indexed.items():
            data['items'].setdefault(key, {'url': p['url'], 'first_seen': now})
        for key,item in data['items'].items():
            post = indexed.get(key)
            item['status'] = ('failed' if post.get('read_state') == 'unavailable' else 'archived') if post else 'discovered'
        if end_evidence:
            data['end_evidence'] = {'description': end_evidence, 'recorded_at': now}
        data['checked_at'] = now
        data['counts'] = {s: sum(i['status']==s for i in data['items'].values()) for s in ('archived','discovered','failed')}
        # Evidence is an operator observation, not an independent completeness guarantee.
        data['all_discovered_archived'] = not (data['counts']['discovered'] or data['counts']['failed'])
        data['platform_total_verified'] = False
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        os.replace(temp,path)
        return data
    finally:
        lock.rmdir()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',required=True,type=Path)
    parser.add_argument('--urls',type=Path,help='UTF-8 text: one observed URL per line')
    parser.add_argument('--account')
    parser.add_argument('--end-evidence',help='Actual observed end marker; never use no-new-items as evidence')
    args=parser.parse_args()
    urls=[u.strip() for u in args.urls.read_text().splitlines() if u.strip()] if args.urls else []
    data=reconcile(args.library,urls,args.account,args.end_evidence)
    print(json.dumps({'counts':data['counts'],'all_discovered_archived':data['all_discovered_archived'],'platform_total_verified':False},ensure_ascii=False))
