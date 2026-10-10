import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch
from viewer.bundle import load_bundle, r6_input


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {'schema_version':'r7-hierarchical-bundle/0.1','bundle_id':'bundle-fixture','kb_revision':'kb-0006','entry_mode':'preinitialized','fixture':True,'files':[]}

    def add(self,role,value):
        path = self.root/(role+'.json')
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        self.manifest['files'].append({'role':role,'path':path.name,'byte_sha256':hashlib.sha256(raw).hexdigest()})
        return path

    def load(self):
        path = self.root/'bundle.json'
        path.write_bytes(json.dumps(self.manifest).encode())
        return load_bundle(path)

    def test_partial_never_promoted_and_fields_retained(self):
        value = {'schema_version':'producer-fixture/0.1','fixture':True,'unknown_preserved':{'angle':.3},'nodes':[]}
        self.add('logical_dag',value)
        _,data,receipt = self.load()
        self.assertEqual(data['logical_dag'],value)
        self.assertEqual(receipt['status'],'byte_verified_partial')
        self.assertFalse(receipt['domain_validation_performed'])
        self.assertFalse(receipt['full_program_passed'])
        self.assertIn('trace',receipt['missing_core_roles'])

    def test_tampering_duplicate_and_escape_rejected(self):
        path = self.add('logical_dag',{'fixture':True})
        original = path.read_bytes()
        path.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):self.load()
        path.write_bytes(original)
        self.manifest['files'].append(copy.deepcopy(self.manifest['files'][0]))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ROLE'):self.load()
        self.manifest['files'].pop()
        self.manifest['files'][0]['path']='../outside.json'
        with self.assertRaisesRegex(ValueError,'PATH_ESCAPE'):self.load()

    def test_old_initialization_and_false_fixture_label_rejected(self):
        self.add('logical_dag',{'fixture':True})
        self.manifest['fixture']=False
        with self.assertRaisesRegex(ValueError,'FIXTURE_MISMATCH'):self.load()
        self.manifest['fixture']=True
        self.add('device',{'zones':{'initialization':{}}})
        with self.assertRaisesRegex(ValueError,'LEGACY_INITIALIZATION_ZONE'):self.load()

    def test_r6_mapping_keeps_original_objects(self):
        values={'atom':{'actions':[]},'physical_dag':{'nodes':[]},'trace':{'results':{}},'placement_evidence':{'raw':[]},'validation':{'passed':True}}
        result=r6_input(values)
        self.assertIs(result['atom_program'],values['atom'])
        self.assertIs(result['physical_dags'][0],values['physical_dag'])
        self.assertNotIn('validation',result)

    def test_duplicate_json_keys_rejected(self):
        path=self.add('logical_dag',{})
        raw=b'{"nodes":[],"nodes":[1]}'
        path.write_bytes(raw)
        self.manifest['files'][0]['byte_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON_KEY'):self.load()

    def test_server_budget_and_entry_are_explicit(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
        from server_pipeline_job import validate_spec
        spec={'schema_version':'r7-server-job/0.1','name':'example','stage_kind':'logical_frontend','argv':['{python}','-m','na_pipeline'],
              'purpose_id':'example','output_roots':['scripts/outputs/T704/run'],'budget':{'wall_seconds':3600,'memory_gib':8,'parallelism':1,'search_expansions':4000100},'budget_rationale':'Complete input; measured stages separately.'}
        validate_spec(spec)
        spec['budget']['memory_gib']=float('nan')
        with self.assertRaisesRegex(ValueError,'BUDGET_REQUIRED'):validate_spec(spec)
        spec['budget']['memory_gib']=8;spec['argv']=['{python}','-c','print(1)']
        with self.assertRaisesRegex(ValueError,'FILE_OR_MODULE_ENTRY_REQUIRED'):validate_spec(spec)

    def test_output_roots_and_distinct_job_identities(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
        from server_pipeline_job import valid_output_roots,identity
        self.assertEqual(valid_output_roots(['examples/atom/t405/run']),['examples/atom/t405/run'])
        for value in ['../escape','C:/outside','/etc','examples/atom/../../../escape']:
            with self.assertRaisesRegex(ValueError,'OUTPUT_ROOT_ESCAPE'):valid_output_roots([value])
        spec={'name':'test','purpose_id':'complete-world','argv':['{python}','-m','na_pipeline'],'budget':{'wall_seconds':100}}
        a=identity(spec,{'input.json':'a'});b=identity(spec,{'input.json':'b'})
        self.assertEqual(a['purpose_id'],b['purpose_id']);self.assertNotEqual(a['exact_job_sha256'],b['exact_job_sha256'])

    def test_readonly_validation_zero_search_and_role_output_root(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
        from server_pipeline_job import validate_spec
        spec={'schema_version':'r7-server-job/0.2','name':'r6-check','stage_kind':'validation','purpose_id':'r6-fixed-stage','argv':['{python}','tests/validation/check.py'],'output_roots':['knowledge/roles/R6/evidence/T605/check'],'budget':{'wall_seconds':3600,'memory_gib':24,'parallelism':1,'search_expansions':0},'budget_rationale':'Read fixed bytes; zero compiler/search calls.'}
        validate_spec(spec)
        spec['stage_kind']='representative_compile'
        with self.assertRaisesRegex(ValueError,'BUDGET_REQUIRED: search_expansions'):validate_spec(spec)

    def test_exclusive_dispatch_lock_rejects_second_request_and_releases(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
        import server_pipeline_job as job
        args=SimpleNamespace(spec=self.root/'spec.json')
        def inner(request):
            self.assertTrue((self.root/'.dispatch.lock').exists())
            with self.assertRaisesRegex(ValueError,'DISPATCH_LOCK_HELD'):job.dispatch(request)
        with patch.object(job,'OUT',self.root),patch.object(job,'_dispatch',inner):job.dispatch(args)
        self.assertFalse((self.root/'.dispatch.lock').exists())


if __name__ == '__main__':unittest.main()
