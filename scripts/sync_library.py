# -*- coding: utf-8 -*-
"""Merge reviewed batches into an immutable, versioned local library (macOS/Linux)."""
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from build_library import validate, render, require, local_file, web_url, renderer_hash


def source_key(url):
    web_url(url)
    u = urlsplit(url)
    host = u.hostname.lower()
    if host in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'):
        match = re.search(r'/status/(\d+)(?:/|$)', u.path)
        if match:
            return 'x:status:' + match.group(1)
    query = [(k,v) for k,v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path or '/', urlencode(sorted(query)), ''))


def clean(data):
    d = copy.deepcopy(data)
    for group in ('posts','prompts','skills'):
        for item in d[group]:
            for key in ('_key','_synced_at'):
                item.pop(key, None)
            if group == 'skills':
                for f in item['files']: f.pop('preview', None)
    d['meta'].pop('updated_at', None)
    return d


def identities(d):
    result = {'posts':{}, 'prompts':{}, 'skills':{}}
    for p in d['posts']: result['posts'][p['id']] = source_key(p['url'])
    for p in d['prompts']:
        explicit = p.get('key')
        result['prompts'][p['id']] = explicit or json.dumps([sorted(result['posts'][i] for i in p['sources']),p['kind'],p['title']], ensure_ascii=False)
    for s in d['skills']: result['skills'][s['id']] = s.get('key') or source_key(s['source'])
    for group, entries in result.items():
        require(len(set(entries.values())) == len(entries), 'Duplicate stable identities: ' + group)
    return result


def merge(old, batch, notes):
    old, batch = clean(old), clean(batch)
    ok, bk = identities(old), identities(batch)
    index = {g:{ok[g][p['id']]:p for p in old[g]} for g in ok}
    mapping = {g:{} for g in ok}
    for g in ok:
        next_id = max((p['id'] for p in old[g]), default=0) + 1
        for p in batch[g]:
            prev = index[g].get(bk[g][p['id']])
            mapping[g][p['id']] = prev['id'] if prev else next_id
            if not prev: next_id += 1
    result = copy.deepcopy(old)
    result['meta'] = {**result['meta'], **batch['meta']}
    stats = {g:{'added':0,'updated':0,'kept':0} for g in ok}
    origins = {}
    rank = {'unavailable':0,'partial':1,'complete':2}
    for g in ok:
        positions = {p['id']:i for i,p in enumerate(result[g])}
        for entry in batch[g]:
            p = copy.deepcopy(entry); key = bk[g][p['id']]
            p['id'] = mapping[g][p['id']]
            prev = index[g].get(key)
            if g == 'posts':
                for rel in ('prompts','skills'):
                    p[rel] = sorted(set((prev or {}).get(rel,[]) + [mapping[rel][i] for i in p[rel]]))
                require(p.get('read_state','partial') in rank, 'Invalid read_state')
                # Missing states from legacy clients must never authorize a rewrite.
                relations = {rel: p[rel] for rel in ('prompts', 'skills')}
                if prev and (not entry.get('read_state') or
                             rank[p['read_state']] < rank[prev.get('read_state','partial')] or
                             p['read_state'] == 'unavailable'):
                    p = copy.deepcopy(prev)
                p.update(relations)
                if prev:
                    p['url'] = prev['url']
                    for field in ('user_note','user_tags'):
                        if field in prev: p[field] = copy.deepcopy(prev[field])
            else:
                p['sources'] = sorted(set((prev or {}).get('sources',[]) + [mapping['posts'][i] for i in p['sources']]))
            if prev:
                result[g][positions[p['id']]] = p
                stats[g]['kept' if p == prev else 'updated'] += 1
            else:
                result[g].append(p); stats[g]['added'] += 1
            if g == 'skills': origins[p['id']] = 'batch'
    for p in result['posts']:
        key = source_key(p['url'])
        if key in notes:
            require(isinstance(notes[key],str), 'notes.json values must be text')
            p['user_note'] = notes[key]
    return result, stats, origins


def active(library):
    link = library/'current'
    if not link.is_symlink():
        require(not link.exists(), 'current must be a managed symlink')
        return None
    target = link.resolve()
    require(target.is_relative_to((library/'versions').resolve()) and (target/'library.json').is_file(), 'Invalid current version')
    return target


def switch(library, target):
    temporary = library/('.current-'+uuid.uuid4().hex)
    try:
        temporary.symlink_to(target.relative_to(library), target_is_directory=True)
        os.replace(temporary, library/'current')
    finally:
        if temporary.is_symlink(): temporary.unlink()


def sync(source, library):
    source, library = source.resolve(), library.resolve()
    require(os.name == 'posix', 'Versioned sync currently requires macOS/Linux symlink support')
    library.mkdir(parents=True,exist_ok=True)
    marker = library/'.bookmark-library.json'
    if not marker.exists():
        require(not any(library.iterdir()), 'Use an empty directory; existing files will not be adopted or overwritten')
        marker.write_text('{"format":2}',encoding='utf-8')
    require(json.loads(marker.read_text()) == {'format':2}, 'Unknown library format')
    lock = library/'.sync-lock'
    try: lock.mkdir()
    except FileExistsError: raise ValueError('Another sync may be running; check the lock before retrying')
    try:
        previous = active(library)
        batch = clean(json.loads(source.read_text(encoding='utf-8')))
        validate(batch,source.parent); identities(batch)
        old = json.loads((previous/'library.json').read_text()) if previous else {'meta':{},'posts':[],'prompts':[],'skills':[]}
        notes_path=library/'notes.json'
        if not notes_path.exists(): notes_path.write_text('{}\n',encoding='utf-8')
        notes=json.loads(notes_path.read_text(encoding='utf-8')); require(isinstance(notes,dict),'Invalid notes.json')
        merged, stats, origins = merge(old,batch,notes)
        # Resolve and hash resources before deciding whether there is a real change.
        files={}
        for s in merged['skills']:
            root=source.parent if origins.get(s['id'])=='batch' else previous
            for name in [s['file']]+[f['path'] for f in s['files']]:
                path=local_file(root,name); digest=hashlib.sha256(path.read_bytes()).hexdigest()
                if name in files: require(files[name][1]==digest,'Resource path collision; give distinct content distinct paths')
                files[name]=(path,digest)
        old_hashes={}
        old_renderer=None
        if previous:
            manifest=json.loads((previous/'核验记录.json').read_text())
            old_hashes={x['path']:x['sha256'] for x in manifest['resources']}
            old_renderer=manifest.get('renderer_hash')
        if previous and old_renderer==renderer_hash() and clean(merged)==clean(old) and old_hashes=={k:v[1] for k,v in files.items()}:
            return {'changed':False,'version':previous.name,'counts':{g:len(merged[g]) for g in ('posts','prompts','skills')},'changes':stats}
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        merged['meta']['updated_at']=now
        with tempfile.TemporaryDirectory(prefix='.sync-work-',dir=library) as td:
            stage=Path(td)
            for name,(path,digest) in files.items():
                dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            (library/'versions').mkdir(exist_ok=True)
            version=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
            destination=library/'versions'/version
            render(merged,stage,destination)
            # Share identical immutable resources across snapshots; never link input files.
            if previous:
                for name, (_, digest) in files.items():
                    if old_hashes.get(name) != digest:
                        continue
                    prior = local_file(previous, name)
                    if hashlib.sha256(prior.read_bytes()).hexdigest() != digest:
                        continue
                    dest = destination/name
                    shared = dest.with_name(dest.name + '.share-' + uuid.uuid4().hex)
                    try:
                        os.link(prior, shared)
                        os.replace(shared, dest)
                    except OSError:
                        pass  # Filesystems without hard links keep an independent copy.
                    finally:
                        if shared.exists(): shared.unlink()
        # Prepare entrypoints before publishing. current is the sole authoritative pointer.
        entry='<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=current/阅读页.html"><title>收藏知识库</title><a href="current/阅读页.html">打开最新阅读页</a>'
        for name in ('index.html','阅读页.html'):
            if not (library/name).exists(): (library/name).write_text(entry,encoding='utf-8')
        (destination/'更新记录.json').write_text(json.dumps({'updated_at':now,'previous':previous.name if previous else None,'changes':stats},ensure_ascii=False,indent=2),encoding='utf-8')
        switch(library,destination)
        return {'changed':True,'version':version,'counts':{g:len(merged[g]) for g in ('posts','prompts','skills')},'changes':stats}
    finally:
        lock.rmdir()


def rollback(library,version):
    library = library.resolve()
    require(re.fullmatch(r'[A-Za-z0-9_-]+',version) is not None,'Invalid version')
    lock=library/'.sync-lock'
    lock.mkdir()
    try:
        target=(library/'versions'/version).resolve()
        require(target.is_relative_to((library/'versions').resolve()) and (target/'library.json').is_file(),'Unknown version')
        validate(json.loads((target/'library.json').read_text()),target)
        switch(library,target)
    finally:lock.rmdir()
    return {'rolled_back_to':version}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',required=True,type=Path)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--input',type=Path)
    action.add_argument('--rollback')
    args=parser.parse_args()
    result=sync(args.input.resolve(),args.library.resolve()) if args.input else rollback(args.library.resolve(),args.rollback)
    print(json.dumps(result,ensure_ascii=False))
