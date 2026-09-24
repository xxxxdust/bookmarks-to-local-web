import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sync_library import sync, rollback, source_key, active

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.src=self.root/'input';self.src.mkdir();self.library=self.root/'library'
        self.data=json.loads((Path(__file__).resolve().parents[1]/'examples/library.json').read_text())
    def tearDown(self):self.tmp.cleanup()
    def run_sync(self,d=None):
        p=self.src/'library.json';p.write_text(json.dumps(d or self.data));return sync(p,self.library)
    def read(self):return json.loads((active(self.library)/'library.json').read_text())
    def test_idempotent(self):
        first=self.run_sync();second=self.run_sync()
        self.assertFalse(second['changed']);self.assertEqual(first['version'],second['version'])
    def test_append_remaps_all_ids(self):
        self.run_sync();d=copy.deepcopy(self.data)
        d['posts'][0]['url']='https://example.com/new'
        result=self.run_sync(d);out=self.read()
        self.assertEqual(result['counts']['posts'],2)
        self.assertEqual(out['posts'][1]['prompts'],[2]);self.assertEqual(out['prompts'][1]['sources'],[2])
    def test_url_aliases(self):
        self.data['posts'][0]['url']='https://twitter.com/a/status/123?s=20';self.run_sync()
        d=copy.deepcopy(self.data);d['posts'][0]['url']='https://x.com/b/status/123?utm_source=test'
        self.assertFalse(self.run_sync(d)['changed'])
    def test_preserve_notes(self):
        self.data['posts'][0]['user_note']='my note';self.run_sync()
        d=copy.deepcopy(self.data);d['posts'][0]['user_note']='overwritten';d['posts'][0]['lead']='new'
        self.run_sync(d);self.assertEqual(self.read()['posts'][0]['user_note'],'my note')
        (self.library/'notes.json').write_text(json.dumps({source_key(d['posts'][0]['url']):'edited note'}))
        self.run_sync(d);self.assertEqual(self.read()['posts'][0]['user_note'],'edited note')
        self.assertIn('edited note',(active(self.library)/'逐篇重点.md').read_text())
    def test_no_downgrade(self):
        self.data['posts'][0]['read_state']='complete';self.run_sync()
        d=copy.deepcopy(self.data);d['posts'][0].update(read_state='unavailable',lead='blocked')
        self.run_sync(d);self.assertNotEqual(self.read()['posts'][0]['lead'],'blocked')
    def test_failure_leaves_current(self):
        version=self.run_sync()['version'];d=copy.deepcopy(self.data);d['posts'][0]['lead']='updated'
        with patch('sync_library.render',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.run_sync(d)
        self.assertEqual(active(self.library).name,version);self.assertFalse((self.library/'.sync-lock').exists())
    def test_rollback(self):
        version=self.run_sync()['version'];d=copy.deepcopy(self.data);d['posts'][0]['lead']='updated';self.run_sync(d)
        rollback(self.library,version);self.assertEqual(active(self.library).name,version)
    def test_missing_resource_leaves_current(self):
        version=self.run_sync()['version'];d=copy.deepcopy(self.data)
        d['skills']=[{'id':1,'name':'test','repository':'test','use':'test','source':'https://example.com/tool','file':'resources/missing.txt','license':'test','commit':'test','sources':[1],'files':[]}]
        with self.assertRaises(ValueError):self.run_sync(d)
        self.assertEqual(active(self.library).name,version)
    def test_resource_content_change(self):
        f=self.src/'resources/a.txt';f.parent.mkdir();f.write_text('old')
        self.data['skills']=[{'id':1,'name':'test','repository':'test','use':'test','source':'https://example.com/tool','file':'resources/a.txt','license':'test','commit':'test','sources':[1],'files':[{'path':'resources/a.txt','label':'a'}]}]
        self.data['posts'][0]['skills']=[1]
        version=self.run_sync()['version'];f.write_text('new');self.assertTrue(self.run_sync()['changed'])
        self.assertEqual((self.library/'versions'/version/'resources/a.txt').read_text(),'old')
        self.assertEqual((active(self.library)/'resources/a.txt').read_text(),'new')
    def test_no_delete_on_empty_batch(self):
        self.run_sync();d=copy.deepcopy(self.data)
        for g in ('posts','prompts','skills'):d[g]=[]
        self.assertFalse(self.run_sync(d)['changed']);self.assertEqual(len(self.read()['posts']),1)
    def test_concurrent_guard(self):
        self.run_sync();(self.library/'.sync-lock').mkdir()
        with self.assertRaises(ValueError):self.run_sync()
    def test_refuse_existing_unmanaged_directory(self):
        self.library.mkdir();(self.library/'important.txt').write_text('keep')
        with self.assertRaises(ValueError):self.run_sync()
        self.assertEqual((self.library/'important.txt').read_text(),'keep')

if __name__=='__main__':unittest.main()
