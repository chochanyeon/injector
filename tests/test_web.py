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
from test_http_observation import artifact
from test_runtime import fixture


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        fixture(root)
        self.selection_file = root / '.local' / 'web-selection.json'
        self.start_server()

    def start_server(self, **kwargs):
        self.server = make_server(self.temporary.name, 0, selection_file=self.selection_file, **kwargs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
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

    def test_server_shutdown_requires_local_control_and_releases_port(self):
        endpoint = '/api/shutdown'
        token = json.loads(self.request('/api/info')[1])['token']
        headers = {'X-Injector-Token': token}
        self.assertEqual(self.request(endpoint)[0], 404)
        self.assertEqual(self.request(endpoint, {})[0], 403)
        self.assertEqual(self.request(endpoint, {}, {**headers, 'Origin': 'https://foreign.test'})[0], 403)
        picker_attempts = []
        with patch('injector_core.web.choose_project_folder',
                   side_effect=lambda _: picker_attempts.append(self.request(endpoint, {}, headers))):
            self.assertEqual(self.request('/api/project/pick', {}, headers)[0], 200)
        self.assertEqual(picker_attempts[0][0], 409)
        with patch('injector_core.web.stop') as stop:
            status, body = self.request(endpoint, {}, headers)
            self.assertEqual((status, json.loads(body)), (200, {'status': 'shutting-down'}))
            self.thread.join(3)
            self.assertFalse(self.thread.is_alive())
            stop.assert_not_called()
        self.server.server_close()
        with make_server(self.temporary.name, self.port) as restarted:
            self.assertEqual(restarted.server_port, self.port)

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
        for profile, catalog_dependencies in (('dummy', ['redis']), ('real', ['redis', 'postgres'])):
            with self.subTest(profile=profile):
                query = urlencode({'project': str(demo), 'profile': profile})
                status, response = self.request('/api/graph?' + query)
                self.assertEqual(status, 200)
                graph = json.loads(response)
                steps = {step['node']: step for step in graph['steps']}
                self.assertEqual(steps['catalog']['variant'], profile)
                self.assertEqual(steps['catalog']['dependencies'], catalog_dependencies)
                self.assertEqual(steps['platform-service']['dependencies'], ['catalog', 'redis', 'vault-mock'])
                self.assertEqual(steps['support-console']['dependencies'], ['catalog', 'vault-mock'])
                self.assertEqual(set(steps), {'platform-service', 'support-console', 'catalog', 'vault-mock',
                                              *catalog_dependencies})

                status, response = self.request('/api/graph?' + query + '&target=support-console')
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(response)['order'],
                                 [*catalog_dependencies, 'catalog', 'vault-mock', 'support-console'])

        query = urlencode({'project': str(demo), 'profile': 'real', 'target': 'platform-service',
                           'variant': 'catalog=dummy'})
        for route in ('plan', 'graph'):
            status, response = self.request(f'/api/{route}?' + query)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(response)['order'], ['redis', 'catalog', 'vault-mock', 'platform-service'])
        self.assertEqual(self.request('/api/plan?' + query + '&variant=catalog=real')[0], 400)
        query = urlencode({'project': str(demo), 'profile': 'dummy', 'target': 'platform-service',
                           'variant': 'catalog=real'})
        status, response = self.request('/api/plan?' + query)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)['order'],
                         ['redis', 'postgres', 'catalog', 'vault-mock', 'platform-service'])

    def test_rejects_foreign_hosts_and_cross_origin_mutations(self):
        self.assertEqual(self.request('/api/info', headers={'Host': 'evil.test'})[0], 403)
        self.assertEqual(self.request('/api/stop', {})[0], 403)
        token = json.loads(self.request('/api/info')[1])['token']
        self.assertEqual(self.request('/api/stop', {}, {'X-Injector-Token': token, 'Origin': 'https://evil.test'})[0], 403)

    def test_execution_check_reports_dependency_blockers_without_preparing(self):
        root = Path(self.temporary.name)
        path = root / 'registry.json'
        data = json.loads(path.read_bytes())
        dependency = data['nodes'][1]['variants']
        dependency['broken'] = {**dependency['local'], 'execution': {
            'type': 'process', 'command': ['./missing-runner'], 'workingDirectory': '.'}}
        dependency['compose'] = {**dependency['local'], 'execution': {
            'type': 'compose', 'file': 'compose.yaml', 'service': 'dependency', 'projectName': 'test'},
            'readiness': {'type': 'compose', 'timeoutSeconds': 3}}
        path.write_text(json.dumps(data), encoding='utf-8')
        (root / 'compose.yaml').touch()
        endpoint = '/api/check'
        body = {'project': self.temporary.name, 'profile': 'dummy', 'target': 'main'}
        token = json.loads(self.request('/api/info')[1])['token']
        headers = {'X-Injector-Token': token}
        self.assertEqual(self.request(endpoint, body)[0], 403)
        status, response = self.request(endpoint, body, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response), {'order': ['dependency', 'main']})

        self.assertEqual(self.request('/api/plan?' + urlencode({**body, 'variant': 'dependency=broken'}))[0], 200)
        status, response = self.request(endpoint, {**body, 'variants': {'dependency': 'broken'}}, headers)
        self.assertEqual(status, 400)
        self.assertIn('dependency: process command', json.loads(response)['error'])

        port = dependency['compose']['endpoints']['http']['addresses']['host']['port']
        config = json.dumps({'services': {'dependency': {'ports': [{'published': str(port), 'target': 8080}]}}})
        with patch('injector_core.runtime._docker', return_value=config) as docker:
            status, response = self.request(endpoint, {**body, 'variants': {'dependency': 'compose'}}, headers)
            self.assertEqual(status, 400)
            self.assertIn('dependency: compose readiness requires a healthcheck', json.loads(response)['error'])
            self.assertEqual(docker.call_args.args, (['compose', '-p', 'test', '-f',
                str(root.resolve() / 'compose.yaml'), 'config', '--format', 'json'],))
            self.assertIn('env', docker.call_args.kwargs)

        data['nodes'][0]['variants']['local']['execution'] = {
            'type': 'intellij', 'projectPath': '.', 'module': 'missing-module', 'mainClass': 'example.Absent'}
        path.write_text(json.dumps(data), encoding='utf-8')
        status, response = self.request(endpoint, body, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)['intellij'],
                         {'module': 'missing-module', 'mainClass': 'example.Absent'})
        self.assertFalse((root / '.local').exists())
        self.assertEqual(json.loads(self.request('/api/job')[1])['status'], 'idle')

    def test_bad_project_path_returns_json_without_disconnect(self):
        status, response = self.request('/api/project?project=%00')
        self.assertEqual(status, 400)
        self.assertIn('error', json.loads(response))

    def test_observation_comparison_preserves_large_json_integers(self):
        baseline, candidate = artifact(), artifact()
        baseline["target"]["fields"]["/id"] = 9007199254740992
        candidate["target"]["fields"]["/id"] = 9007199254740993
        path = "/api/observations/compare"
        body = {"baseline": json.dumps(baseline), "candidate": json.dumps(candidate)}
        self.assertEqual(self.request(path, body)[0], 403)
        headers = {"X-Injector-Token": json.loads(self.request("/api/info")[1])["token"]}
        status, response = self.request(path, body, headers)
        result = json.loads(response)
        self.assertEqual(status, 200)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("9007199254740993", result["candidate"])
        self.assertEqual(result["changes"], [{"path": "/target/fields/~1id", "kind": "changed"}])

    def test_loaded_selection_is_restored_across_server_restarts(self):
        root = Path(self.temporary.name).resolve()
        worktree = root / 'another worktree'
        worktree.mkdir()
        registry = (root / 'registry.json').rename(root / 'local settings.json')
        initial = json.loads(self.request('/api/info')[1])
        headers = {'X-Injector-Token': initial['token']}
        selected = {'project': str(worktree), 'registry': str(registry)}
        self.assertEqual(self.request('/api/project', selected)[0], 403)
        self.assertEqual(self.request('/api/project?' + urlencode(selected))[0], 200)
        self.assertFalse(self.selection_file.exists())
        self.assertEqual(self.request('/api/project', selected, headers)[0], 200)
        self.assertEqual(json.loads(self.selection_file.read_bytes()), selected)
        self.assertEqual(self.request('/api/project', {**selected, 'registry': str(root / 'missing')}, headers)[0], 400)
        self.assertEqual(json.loads(self.selection_file.read_bytes()), selected)
        self.assertEqual(list(worktree.iterdir()), [])

        self.stop_server()
        self.start_server()
        restored = json.loads(self.request('/api/info')[1])
        self.assertEqual({key: restored[key] for key in selected}, selected)
        self.assertNotEqual(restored['token'], initial['token'])
        self.assertEqual(self.request('/api/project')[0], 200)
        self.assertEqual(json.loads(self.request('/api/job')[1])['status'], 'idle')

        self.stop_server()
        self.start_server(registry=registry, restore_selection=False)
        explicit = json.loads(self.request('/api/info')[1])
        self.assertEqual(explicit['project'], str(root))
        self.assertEqual(explicit['registry'], str(registry))
        self.assertEqual(json.loads(self.selection_file.read_bytes()), selected)

        registry.unlink()
        self.stop_server()
        self.start_server()
        info = json.loads(self.request('/api/info')[1])
        self.assertEqual({key: info[key] for key in selected}, selected)
        self.assertEqual(self.request('/api/project')[0], 400)

    def test_malformed_saved_selection_falls_back_to_startup_default(self):
        self.selection_file.parent.mkdir()
        self.selection_file.write_text('{', encoding='utf-8')
        self.stop_server()
        self.start_server()
        info = json.loads(self.request('/api/info')[1])
        self.assertEqual(info['project'], str(Path(self.temporary.name).resolve()))
        self.assertEqual(info['registry'], '')
        self.assertEqual(self.request('/api/project')[0], 200)

    def registry_request(self, action, **payload):
        token = json.loads(self.request('/api/info')[1])['token']
        body = {'project': self.temporary.name, **payload}
        status, response = self.request('/api/registry/' + action, body, {'X-Injector-Token': token})
        return status, json.loads(response)

    def test_project_folder_picker_requires_token_and_handles_selection(self):
        endpoint = '/api/project/pick'
        project = Path(self.temporary.name).resolve()
        token = json.loads(self.request('/api/info')[1])['token']
        headers = {'X-Injector-Token': token}
        body = {'project': str(project)}
        with patch('injector_core.web.choose_project_folder') as picker:
            self.assertEqual(self.request(endpoint, body)[0], 403)
            self.assertEqual(self.request(endpoint, body, {**headers, 'Origin': 'https://evil.test'})[0], 403)
            picker.assert_not_called()
            clean_worktree = project / 'worktree'
            clean_worktree.mkdir()
            for selected in (None, str(project), str(clean_worktree)):
                picker.return_value = selected
                status, response = self.request(endpoint, body, headers)
                self.assertEqual((status, json.loads(response)), (200, {'project': selected}))
                picker.assert_called_with(str(project))
            picker.return_value = str(project / 'missing')
            self.assertEqual(self.request(endpoint, body, headers)[0], 400)

    def test_central_registry_editor_catalog_and_graph_use_the_selected_worktree(self):
        storage = Path(self.temporary.name).resolve()
        worktree = storage / 'source tree'
        worktree.mkdir()
        default = storage / 'registry.json'
        original = default.read_bytes()
        selected = storage / 'local settings.json'
        selected.write_bytes(original)
        params = {'project': str(worktree), 'registry': str(selected)}
        for registry, expected in ((storage, default), (default, default), (selected, selected)):
            query = urlencode({**params, 'registry': str(registry)})
            status, catalog = self.request('/api/project?' + query)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(catalog)['registry'], str(expected))
        query = urlencode(params)
        graph_status, graph = self.request('/api/graph?' + query + '&profile=dummy')
        self.assertEqual(graph_status, 200)
        self.assertEqual(json.loads(graph)['order'], ['dependency', 'main'])
        status, opened = self.registry_request('open', **params)
        self.assertEqual(status, 200)
        self.assertEqual(opened['path'], str(selected))
        data = json.loads(opened['text'])
        data['profiles']['local'] = data['profiles']['dummy']
        status, saved = self.registry_request('save', **params, text=json.dumps(data), revision=opened['revision'])
        self.assertEqual(status, 200)
        self.assertEqual(saved['registry'], str(selected))
        self.assertIn('local', json.loads(selected.read_bytes())['profiles'])
        self.assertEqual(default.read_bytes(), original)
        self.assertFalse(list(worktree.iterdir()))

    def test_registry_picker_accepts_files_and_load_checks_the_content(self):
        storage = Path(self.temporary.name).resolve()
        registry = storage / 'registry.json'
        other = storage / 'other registry'
        other.write_text('{}', encoding='utf-8')
        token = json.loads(self.request('/api/info')[1])['token']
        headers = {'X-Injector-Token': token}
        body = {'kind': 'registry', 'project': str(registry)}
        endpoint = '/api/project/pick'
        with patch('injector_core.web.choose_registry_file') as picker:
            self.assertEqual(self.request(endpoint, body)[0], 403)
            picker.assert_not_called()
            for selected in (None, str(registry), str(other)):
                picker.return_value = selected
                status, response = self.request(endpoint, body, headers)
                self.assertEqual((status, json.loads(response)), (200, {'project': selected}))
                picker.assert_called_with(str(registry))
            for selected in (storage, storage / 'missing' / 'registry.json'):
                picker.return_value = str(selected)
                self.assertEqual(self.request(endpoint, body, headers)[0], 400)
        query = urlencode({'project': str(storage), 'registry': str(other)})
        status, response = self.request('/api/project?' + query)
        self.assertEqual(status, 400)
        self.assertIn('unsupported schemaVersion', json.loads(response)['error'])

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

    def test_registry_editor_repairs_a_declared_node_file_without_rewriting_root(self):
        root = Path(self.temporary.name)
        registry = root / 'registry.json'
        data = json.loads(registry.read_text(encoding='utf-8'))
        node = data['nodes'].pop(0)
        data['nodeFiles'] = ['app.json']
        original = json.dumps(data).encode()
        registry.write_bytes(original)
        filename = root / 'app.json'
        filename.write_text('{"id":', encoding='utf-8')
        status, opened = self.registry_request('open')
        self.assertEqual(status, 200)
        self.assertEqual(opened['files'], ['app.json'])
        self.assertEqual(self.request('/api/project')[0], 400)
        self.assertEqual(self.registry_request('open', file='other.json')[0], 400)
        status, opened = self.registry_request('open', file='app.json')
        self.assertEqual(status, 200)
        self.assertEqual(opened['text'], '{"id":')
        body = {'file': 'app.json', 'text': json.dumps(node), 'revision': opened['revision']}
        self.assertEqual(self.registry_request('validate', **body)[0], 200)
        self.assertEqual(filename.read_text(encoding='utf-8'), '{"id":')
        self.assertEqual(self.registry_request('save', **body)[0], 200)
        self.assertEqual(self.registry_request('save', **body)[0], 409)
        self.assertEqual(registry.read_bytes(), original)
        self.assertEqual(json.loads(filename.read_text(encoding='utf-8')), node)
        self.assertEqual(self.request('/api/project')[0], 200)

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

    def test_registry_completion_lists_and_adds_paths_in_the_selected_registry(self):
        source = Path(self.temporary.name)
        storage = source / 'settings'
        nodes = storage / 'nodes'
        nodes.mkdir(parents=True)
        registry = storage / 'my-registry.json'
        data = json.loads((source / 'registry.json').read_bytes())
        candidate = {**data['nodes'][1], 'id': 'warehouse'}
        text = json.dumps(data, indent=2) + '\n'
        registry.write_text(text, encoding='utf-8')
        path = 'nodes/local warehouse.JSON'
        node_file = storage / path
        node_file.write_text(json.dumps(candidate), encoding='utf-8')
        (nodes / 'duplicate.json').write_text(json.dumps(data['nodes'][0]), encoding='utf-8')
        (nodes / 'not-a-node.json').write_text('{}', encoding='utf-8')
        (source / 'outside.json').write_text(json.dumps(candidate), encoding='utf-8')
        params = {'registry': str(registry), 'text': text}
        self.assertEqual(self.request('/api/registry/complete', {'project': str(source), **params})[0], 403)
        self.assertEqual(self.registry_request('complete', **params), (200, {
            'paths': [{'path': path, 'id': 'warehouse'}], 'limited': False}))
        self.assertEqual(self.registry_request('complete', **params, edit={'path': '../outside.json'})[0], 400)
        status, result = self.registry_request('complete', **params, edit={'path': path})
        self.assertEqual(status, 200)
        self.assertTrue(result['text'].startswith(text.rstrip()[:-2]))
        self.assertEqual(json.loads(result['text']), {**data, 'nodeFiles': [path]})
        self.assertEqual(registry.read_text(encoding='utf-8'), text)
        updated = {**params, 'text': result['text']}
        self.assertEqual(self.registry_request('complete', **updated)[1]['paths'], [])
        self.assertEqual(self.registry_request('complete', **updated, edit={'path': path})[0], 400)
        _, opened = self.registry_request('open', registry=str(registry))
        self.assertEqual(self.registry_request('save', **updated, revision=opened['revision'])[0], 200)
        self.assertEqual(json.loads(registry.read_bytes())['nodeFiles'], [path])
        self.assertEqual(json.loads(node_file.read_bytes()), candidate)

    def test_registry_completion_uses_node_variants_and_preserves_unrelated_json(self):
        root = Path(self.temporary.name)
        registry = root / 'registry.json'
        data = json.loads(registry.read_bytes())
        data['schemaVersion'] = '1.1'
        node = data['nodes'].pop(0)
        original = node['variants']['local']
        original['springProperties'] = {'app.id': 9007199254740993, 'app.rate': 1e-10}
        data['nodeFiles'] = ['main.json']
        data['nodes'].append({**data['nodes'][0], 'id': 'redis'})
        data['profiles']['dummy']['selections']['redis'] = 'local'
        registry.write_text(json.dumps(data), encoding='utf-8')
        text = json.dumps(node, indent=2).replace('1e-10', '1.0000e-10') + '\n'
        path = root / 'main.json'
        path.write_text(text, encoding='utf-8')
        params = {'file': path.name, 'text': text}
        status, choices = self.registry_request('complete', **params)
        self.assertEqual(status, 200)
        variant = choices['variants'][0]
        self.assertEqual(variant['dependencies'], ['redis'])
        self.assertEqual(variant['sources'], [{'id': 'dependency', 'endpoints': [{'id': 'http', 'contexts': [
            {'id': 'host', 'components': ['url', 'host', 'port']}]}]}])
        self.assertIn('springProperty', choices['channels'])
        for field, value in (
            ('dependencies', 'redis'),
            ('injections', {'channel': 'springProperty', 'key': 'app.redis', 'source': {
                'node': 'redis', 'endpoint': 'http', 'context': 'host', 'component': 'url'}}),
            ('execution', {'type': 'intellij', 'projectPath': '.', 'module': 'local', 'mainClass': 'example.Main'}),
        ):
            status, result = self.registry_request('complete', **params,
                                                   edit={'variant': 'local', 'field': field, 'value': value})
            self.assertEqual(status, 200, result)
            self.assertIn('9007199254740993', result['text'])
            self.assertIn('1.0000e-10', result['text'])
            params['text'] = result['text']
        self.assertEqual(path.read_text(encoding='utf-8'), text)
        self.assertEqual(self.registry_request('validate', **params)[0], 200)
        updated = json.loads(params['text'])['variants']['local']
        self.assertEqual(updated['dependencies'], ['dependency', 'redis'])
        self.assertEqual(updated['injections'][0]['key'], 'app.redis')
        self.assertEqual(updated['execution']['type'], 'intellij')

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
        def fake(project, target, profile, emit, variants, registry):
            emit({'node': target, 'phase': 'ready'})
            return {'status': 'ready'}
        with patch('injector_core.web.prepare', side_effect=fake) as runner:
            status, _ = self.request('/api/prepare', {'target': 'main', 'profile': 'dummy',
                                                     'variants': {'dependency': 'mock'}}, {'X-Injector-Token': token})
            self.assertEqual(status, 202)
            for _ in range(100):
                job = json.loads(self.request('/api/job')[1])
                if job['status'] != 'running':
                    break
                time.sleep(.01)
            self.assertEqual(job['status'], 'succeeded')
            self.assertEqual(job['events'], [{'node': 'main', 'phase': 'ready'}])
            runner.assert_called_once()
            self.assertEqual(runner.call_args.kwargs['variants'], {'dependency': 'mock'})

    def test_suite_web_uses_verifier_and_preserves_a_blocked_report(self):
        from verifier.worktree_suite import SuitePreflightError

        token = json.loads(self.request('/api/info')[1])['token']
        headers = {'X-Injector-Token': token}
        root = Path(self.temporary.name).resolve()
        body = {'project': str(root), 'candidate': str(root / 'candidate'), 'suite': str(root / 'suite.json')}
        report = {'phase': 'preflight', 'status': 'BLOCKED', 'diagnostics': [{'code': 'invalid_suite', 'message': 'bad suite'}]}
        (root / 'suite.json').write_text('{}', encoding='utf-8')
        with patch('injector_core.web.choose_suite_file', return_value=body['suite']) as picker:
            status, chosen = self.request('/api/project/pick', {'kind': 'suite'}, headers)
            self.assertEqual((status, json.loads(chosen)['project']), (200, body['suite']))
            picker.assert_called_once_with(str(root))
        self.assertEqual(self.request('/api/suite/check', body)[0], 403)
        with patch('verifier.worktree_suite.check_suite', return_value=report) as checker:
            status, content = self.request('/api/suite/check', body, headers)
            self.assertEqual((status, json.loads(content)), (200, report))
            checker.assert_called_once_with(root / 'suite.json', root, root / 'candidate', registry=None)
        with patch('verifier.worktree_suite.verify_suite', side_effect=SuitePreflightError(report)) as runner:
            self.assertEqual(self.request('/api/suite/run', body, headers)[0], 202)
            for _ in range(100):
                job = json.loads(self.request('/api/job')[1])
                if job['status'] != 'running':
                    break
                time.sleep(.01)
            self.assertEqual(job['action'], 'suite')
            self.assertEqual(job['result'], report)
            self.assertEqual(job['context']['candidate'], body['candidate'])
            runner.assert_called_once()

    def test_saved_suite_history_survives_restart_and_limits_report_reads(self):
        root = Path(self.temporary.name).resolve()
        evidence = root / 'evidence'
        case = {'scenario': 'checkout', 'verdict': 'FAIL', 'report': '01/report.json'}
        report = {'schemaVersion': 1, 'suite': 'shop', 'targetApp': 'orders', 'profile': 'local',
                  'verdict': 'FAIL', 'cases': [case, {'scenario': 'skipped', 'verdict': 'NOT_RUN'}]}
        projects = {'baseline': str(root), 'candidate': str(root / 'candidate')}
        comparison = {'verdict': 'FAIL', 'baseline': {'order/id': [9007199254740993]},
                      'candidate': {'order/id': [9007199254740992]},
                      'changes': [{'kind': 'changed', 'path': '/order~1id/0'}],
                      'runs': {side: {'project': path} for side, path in projects.items()}}

        def write(run, suite):
            folder = evidence / run
            (folder / '01').mkdir(parents=True)
            (folder / 'report.json').write_text(json.dumps(suite), encoding='utf-8')
            (folder / '01' / 'report.json').write_text(json.dumps(comparison), encoding='utf-8')

        write('a' * 16, {**report, 'worktrees': projects})
        write('b' * 16, report)
        write('c' * 16, {**report, 'worktrees': {**projects, 'baseline': str(root / 'different')}})

        with patch('injector_core.web.VERIFICATION_RUNS', evidence):
            self.stop_server()
            self.start_server()
            token = json.loads(self.request('/api/info')[1])['token']
            headers = {'X-Injector-Token': token}
            path, selection = '/api/suite/history', {'project': str(root)}
            self.assertEqual(self.request(path, selection)[0], 403)
            status, content = self.request(path, selection, headers)
            self.assertEqual(status, 200)
            self.assertEqual({run['id'] for run in json.loads(content)['runs']}, {'a' * 16, 'b' * 16})
            status, content = self.request(path, {**selection, 'run': 'b' * 16}, headers)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(content)['worktrees'], projects)
            status, content = self.request(path, {**selection, 'run': 'a' * 16, 'case': 1}, headers)
            self.assertEqual(status, 200)
            self.assertIn('9007199254740993', json.loads(content)['baseline'])
            change = json.loads(content)['changes'][0]
            self.assertEqual((change['baseline'], change['candidate']), ('9007199254740993', '9007199254740992'))
            for input_body in ({'run': '../evidence'}, {'run': 'c' * 16}, {'run': 'a' * 16, 'case': 2}):
                self.assertEqual(self.request(path, {**selection, **input_body}, headers)[0], 400)

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
        def waiting(*args, **kwargs):
            gate.wait(3)
            finished.set()
            return {'status': 'stopped'}
        with patch('injector_core.web.stop', side_effect=waiting):
            try:
                self.assertEqual(self.request('/api/stop', {}, headers)[0], 202)
                self.assertEqual(self.request('/api/stop', {}, headers)[0], 400)
                status, response = self.request('/api/shutdown', {}, headers)
                self.assertEqual(status, 409)
                self.assertIn('실행 중인 작업', json.loads(response)['error'])
            finally:
                gate.set()
                self.assertTrue(finished.wait(3))
