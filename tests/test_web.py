import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from injector_core.web import make_server
from test_runtime import fixture


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        fixture(Path(self.temporary.name))
        self.server = make_server(self.temporary.name, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port)
        connection.request('GET' if body is None else 'POST', path,
                           body=json.dumps(body) if body is not None else None, headers=headers or {})
        response = connection.getresponse()
        content = response.read()
        connection.close()
        return response.status, content

    def test_assets_catalog_and_plan(self):
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/app.js')[0], 200)
        self.assertEqual(self.request('/graph.js')[0], 200)
        self.assertEqual(self.request('/../registry.json')[0], 404)
        status, body = self.request('/api/project')
        self.assertEqual(status, 200)
        self.assertIn('main', json.loads(body)['profiles']['dummy']['applications'])

    def test_loopback_startup_does_not_need_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=AssertionError('unexpected DNS lookup')):
            with make_server(self.temporary.name, 0) as server:
                self.assertEqual(server.server_name, '127.0.0.1')
                self.assertGreater(server.server_port, 0)

    def test_dependency_graph_shows_all_selected_apps_and_shared_nodes(self):
        path = Path(self.temporary.name) / 'registry.json'
        data = json.loads(path.read_bytes())
        sibling = {**data['nodes'][0], 'id': 'sibling'}
        data['nodes'].extend([sibling, {**sibling, 'id': 'inactive'}])
        data['profiles']['dummy']['selections']['sibling'] = 'local'
        path.write_text(json.dumps(data), encoding='utf-8')
        query = urlencode({'project': self.temporary.name, 'profile': 'dummy'})
        status, response = self.request('/api/graph?' + query)
        self.assertEqual(status, 200)
        graph = json.loads(response)
        self.assertEqual(graph['targets'], ['main', 'sibling'])
        self.assertEqual(graph['order'], ['dependency', 'main', 'sibling'])
        self.assertEqual(
            {step['node']: step['dependencies'] for step in graph['steps']},
            {'dependency': [], 'main': ['dependency'], 'sibling': ['dependency']})
        self.assertNotIn(b'injected value', response)
        self.assertFalse((path.parent / '.local').exists())

        status, response = self.request('/api/graph?' + query + '&target=sibling')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)['order'], ['dependency', 'sibling'])

    def test_dependency_graph_matches_profile_variants(self):
        demo = Path(__file__).resolve().parents[1] / 'examples' / 'demo'
        for profile in ('dummy', 'real'):
            with self.subTest(profile=profile):
                query = urlencode({'project': str(demo), 'profile': profile, 'target': 'platform-service'})
                status, response = self.request('/api/graph?' + query)
                self.assertEqual(status, 200)
                steps = {step['node']: step for step in json.loads(response)['steps']}
                self.assertEqual(steps['catalog']['variant'], profile)
                self.assertEqual(steps['catalog']['dependencies'], ['redis'])
                self.assertEqual(steps['platform-service']['dependencies'], ['catalog', 'redis'])

    def test_rejects_foreign_hosts_and_cross_origin_mutations(self):
        self.assertEqual(self.request('/api/info', headers={'Host': 'evil.test'})[0], 403)
        self.assertEqual(self.request('/api/stop', {})[0], 403)
        token = json.loads(self.request('/api/info')[1])['token']
        self.assertEqual(self.request('/api/stop', {}, {'X-Injector-Token': token, 'Origin': 'https://evil.test'})[0], 403)

    def registry_request(self, action, **payload):
        token = json.loads(self.request('/api/info')[1])['token']
        body = {'project': self.temporary.name, **payload}
        status, response = self.request('/api/registry/' + action, body, {'X-Injector-Token': token})
        return status, json.loads(response)

    def test_registry_editor_repairs_invalid_file_and_refreshes_catalog(self):
        path = Path(self.temporary.name) / 'registry.json'
        data = json.loads(path.read_bytes())
        data['profiles']['updated'] = data['profiles'].pop('dummy')
        corrected = json.dumps(data, indent=2) + '\n'
        broken = b'{\r\n bad'
        path.write_bytes(broken)
        status, opened = self.registry_request('open')
        self.assertEqual(status, 200)
        self.assertEqual(opened['text'], broken.decode())
        self.assertEqual(self.request('/api/project')[0], 400)

        rejected, error = self.registry_request('save', text=opened['text'], revision=opened['revision'])
        self.assertEqual(rejected, 400)
        self.assertIn('line 2, column 2', error['error'])
        self.assertEqual(path.read_bytes(), broken)
        self.assertEqual(self.registry_request('validate', text=corrected)[0], 200)
        self.assertEqual(path.read_bytes(), broken)

        status, saved = self.registry_request('save', text=corrected, revision=opened['revision'])
        self.assertEqual(status, 200)
        self.assertNotEqual(saved['revision'], opened['revision'])
        self.assertEqual(path.read_bytes(), corrected.replace('\n', '\r\n').encode())
        self.assertIn('updated', json.loads(self.request('/api/project')[1])['profiles'])

    def test_registry_editor_validates_schema_references_and_cycles(self):
        original = json.loads((Path(self.temporary.name) / 'registry.json').read_bytes())
        for key, pattern in (('schema', '/nodes/0'), ('missing', 'unknown dependency'), ('cycle', 'dependency cycle')):
            with self.subTest(key=key):
                data = json.loads(json.dumps(original))
                if key == 'schema':
                    data['nodes'][0]['kind'] = 'wrong'
                else:
                    data['nodes'][1]['variants']['local']['dependencies'] = ['main' if key == 'cycle' else 'unknown']
                status, result = self.registry_request('validate', text=json.dumps(data))
                self.assertEqual(status, 400)
                self.assertIn(pattern, result['error'])

    def test_registry_editor_protects_raw_reads_and_concurrent_edits(self):
        self.assertEqual(self.request('/api/registry/open', {'project': self.temporary.name})[0], 403)
        token = json.loads(self.request('/api/info')[1])['token']
        self.assertEqual(self.request('/api/registry/save', {}, {
            'X-Injector-Token': token, 'Origin': 'https://evil.test'})[0], 403)

        _, opened = self.registry_request('open')
        path = Path(self.temporary.name) / 'registry.json'
        edited = path.read_bytes() + b'\n'
        path.write_bytes(edited)
        status, reason = self.registry_request('save', text=opened['text'] + '\t', revision=opened['revision'])
        self.assertEqual(status, 409)
        self.assertIn('changed on disk', reason['error'])
        self.assertEqual(path.read_bytes(), edited)

    def test_job_uses_runtime_and_reports_progress(self):
        token = json.loads(self.request('/api/info')[1])['token']
        def fake(project, target, profile, emit):
            emit({'node': target, 'phase': 'ready'})
            return {'status': 'ready'}
        with patch('injector_core.web.prepare', side_effect=fake) as runner:
            status, _ = self.request('/api/prepare', {'target': 'main', 'profile': 'dummy'}, {'X-Injector-Token': token})
            self.assertEqual(status, 202)
            for _ in range(100):
                job = json.loads(self.request('/api/job')[1])
                if job['status'] != 'running':
                    break
                time.sleep(.01)
            self.assertEqual(job['status'], 'succeeded')
            self.assertEqual(job['events'], [{'node': 'main', 'phase': 'ready'}])
            runner.assert_called_once()

    def test_errors_do_not_expose_unexpected_exception_values(self):
        token = json.loads(self.request('/api/info')[1])['token']
        with patch('injector_core.web.stop', side_effect=OSError('secret-value')):
            self.request('/api/stop', {}, {'X-Injector-Token': token})
            for _ in range(100):
                job = json.loads(self.request('/api/job')[1])
                if job['status'] != 'running':
                    break
                time.sleep(.01)
            self.assertEqual(job['status'], 'failed')
            self.assertNotIn('secret-value', job['error'])

    def test_rejects_overlapping_jobs(self):
        token = json.loads(self.request('/api/info')[1])['token']
        headers = {'X-Injector-Token': token}
        gate = threading.Event()
        finished = threading.Event()
        def waiting(*args):
            gate.wait(3)
            finished.set()
            return {'status': 'stopped'}
        with patch('injector_core.web.stop', side_effect=waiting):
            try:
                self.assertEqual(self.request('/api/stop', {}, headers)[0], 202)
                self.assertEqual(self.request('/api/stop', {}, headers)[0], 400)
            finally:
                gate.set()
                self.assertTrue(finished.wait(3))
