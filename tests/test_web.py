import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

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
        self.assertEqual(self.request('/../registry.json')[0], 404)
        status, body = self.request('/api/project')
        self.assertEqual(status, 200)
        self.assertIn('main', json.loads(body)['profiles']['dummy']['applications'])

    def test_loopback_startup_does_not_need_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=AssertionError('unexpected DNS lookup')):
            with make_server(self.temporary.name, 0) as server:
                self.assertEqual(server.server_name, '127.0.0.1')
                self.assertGreater(server.server_port, 0)

    def test_rejects_foreign_hosts_and_cross_origin_mutations(self):
        self.assertEqual(self.request('/api/info', headers={'Host': 'evil.test'})[0], 403)
        self.assertEqual(self.request('/api/stop', {})[0], 403)
        token = json.loads(self.request('/api/info')[1])['token']
        self.assertEqual(self.request('/api/stop', {}, {'X-Injector-Token': token, 'Origin': 'https://evil.test'})[0], 403)

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
