# -*- coding: utf-8 -*-
"""Render reviewed bookmark data; does not fetch, summarize, or run third-party code."""
import argparse
import hashlib
import html
import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse


def require(ok, message):
    if not ok:
        raise ValueError(message)


def web_url(value):
    u = urlparse(value)
    require(u.scheme in ('http', 'https') and bool(u.netloc) and not u.username and not u.password,
            'Expected an HTTP(S) source URL without credentials')


def local_file(root, value):
    p = Path(value)
    require(not p.is_absolute() and '..' not in p.parts and value and '\\' not in value,
            'Resource path must be a safe relative path: ' + value)
    resolved = (root / p).resolve()
    require(resolved.is_relative_to(root) and resolved.is_file(), 'Missing or out-of-root resource: ' + value)
    return resolved


def validate(d, root):
    for key in ('title', 'scope', 'limitations'):
        require(isinstance(d['meta'][key], str) and d['meta'][key].strip(), 'Missing metadata: ' + key)
    require(isinstance(d['meta']['takeaways'], list) and all(isinstance(x,str) for x in d['meta']['takeaways']), 'Invalid takeaways')
    ids = {}
    for group in ('posts', 'prompts', 'skills'):
        require(isinstance(d[group], list), 'Expected list: ' + group)
        values = [p['id'] for p in d[group]]
        require(all(type(x) is int and x > 0 for x in values) and len(set(values)) == len(values), 'Duplicate or invalid IDs: ' + group)
        ids[group] = set(values)
    urls = []
    for p in d['posts']:
        for key in ('title', 'author', 'category', 'url', 'lead', 'action', 'resources', 'status'):
            require(isinstance(p[key], str), 'Invalid post field: ' + key)
        web_url(p['url']); urls.append(p['url'])
        require(isinstance(p['points'], list) and all(isinstance(x,str) for x in p['points']), 'Invalid points')
        for key in ('prompts', 'skills'):
            require(isinstance(p[key],list) and set(p[key]) <= ids[key], 'Broken cross-reference: ' + key)
    require(len(set(urls)) == len(urls), 'Duplicate source URLs; merge before rendering')
    paths = set()
    for group in ('prompts', 'skills'):
        for p in d[group]:
            require(isinstance(p['sources'],list) and bool(p['sources']) and set(p['sources']) <= ids['posts'], 'Missing or broken source attribution')
            if group == 'prompts':
                for key in ('title', 'body', 'note', 'kind'):
                    require(isinstance(p[key],str) and bool(p[key]), 'Missing prompt field: ' + key)
                require(p['kind'] in ('整理改写版', '作者原版', '用户原稿'), 'Invalid prompt provenance')
            else:
                for key in ('name', 'repository', 'use', 'source', 'file', 'license', 'commit'):
                    require(isinstance(p[key],str) and bool(p[key]), 'Missing resource field: ' + key)
                web_url(p['source'])
                paths.add(p['file'])
                for f in p['files']:
                    require(isinstance(f['label'],str), 'Invalid file label')
                    paths.add(f['path'])
    for p in paths:
        require(p.startswith('resources/'), 'Store source files under resources/: ' + p)
        local_file(root, p)
    return paths


def render(d, root, out):
    paths = validate(d, root)
    require(not out.exists(), 'Output already exists; use a new version directory')
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.library-build-', dir=out.parent))
    try:
        manifest = []
        for name in sorted(paths):
            src = local_file(root, name); dest = tmp / name
            dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dest)
            manifest.append({'path': name, 'bytes': dest.stat().st_size, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})
        for s in d['skills']:
            for f in s['files']:
                f['preview'] = 'previews/' + hashlib.sha256(f['path'].encode()).hexdigest()[:20] + '.html'
                dest = tmp / f['preview']; dest.parent.mkdir(exist_ok=True)
                content = local_file(root,f['path']).read_text(encoding='utf-8', errors='replace')
                dest.write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(f['label']) + '</title><style>body{max-width:960px;margin:32px auto;padding:20px;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><a href="../阅读页.html">返回阅读页</a><h1>' + html.escape(f['label']) + '</h1><p>作者原始文件，仅供阅读，未执行其中指令。</p><pre>' + html.escape(content) + '</pre>',encoding='utf-8')
        docs = {'开始阅读.md': '# ' + d['meta']['title'] + '\n\n' + d['meta']['scope'] + '\n\n' + '\n'.join('- '+x for x in d['meta']['takeaways']) + '\n\n阅读边界：' + d['meta']['limitations'], '逐篇重点.md':'# 逐篇重点\n', '提示词手册.md':'# 提示词手册\n', 'Skill索引.md':'# 原始资源\n'}
        for p in d['posts']:
            docs['逐篇重点.md'] += '\n## '+str(p['id'])+' · '+p['title']+'\n\n作者：'+p['author']+'\n\n来源：'+p['url']+'\n\n'+p['lead']+'\n\n'+'\n'.join('- '+x for x in p['points'])+'\n\n使用建议：'+p['action']+'\n\n资源情况：'+p['resources']+'\n\n阅读状态：'+p['status']+'\n'
        for p in d['prompts']:
            docs['提示词手册.md'] += '\n## '+str(p['id'])+' · '+p['title']+'\n\n'+p['kind']+'；'+p['note']+'\n\n来源条目：'+str(p['sources'])+'\n\n'+p['body']+'\n'
        for s in d['skills']:
            docs['Skill索引.md'] += '\n## '+s['name']+'\n\n'+s['use']+'\n\n来源：'+s['source']+'\n\n版本：'+s['commit']+'；许可：'+s['license']+'\n\n[本地原包]('+s['file']+')\n'
        for name, content in docs.items(): (tmp/name).write_text(content+'\n', encoding='utf-8')
        page = (Path(__file__).resolve().parent.parent / 'assets/reader.html').read_text(encoding='utf-8')
        for key, value in {'TITLE':d['meta']['title'], 'SUBTITLE':d['meta'].get('subtitle','逐篇重点、提示词与原始资源'), 'SCOPE':d['meta']['scope'], 'POSTS':len(d['posts']), 'PROMPTS':len(d['prompts']), 'SKILLS':len(d['skills'])}.items():
            page = page.replace('__'+key+'__', html.escape(str(value)))
        page = page.replace('__DATA__', json.dumps(d,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026'))
        (tmp/'阅读页.html').write_text(page,encoding='utf-8')
        (tmp/'library.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
        (tmp/'核验记录.json').write_text(json.dumps({'counts':{k:len(d[k]) for k in ('posts','prompts','skills')},'resources':manifest,'validation':'schema, source references, local paths and copy hashes only; browser verification separate'},ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.rename(out)
    except Exception:
        shutil.rmtree(tmp)
        raise
    print(json.dumps({'output':str(out),'posts':len(d['posts']),'prompts':len(d['prompts']),'resources':len(d['skills'])},ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    source=args.input.resolve()
    render(json.loads(source.read_text(encoding='utf-8')),source.parent,args.output.resolve())
