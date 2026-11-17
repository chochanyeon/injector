import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

import psutil

from injector_core.registry import RegistryError
from injector_core.runtime import _directory, _lock, prepare, select_plan, stop


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def process_variant(port, dependencies=(), delay=0):
    script = ("import http.server,os,socket,time; "
              f"time.sleep({delay}); "
              "socket.getfqdn=lambda host:host; "
              "handler=http.server.BaseHTTPRequestHandler; "
              "handler.do_GET=lambda s:(s.send_response(200),s.end_headers(),"
              "s.wfile.write(os.environ.get('PROBE_VALUE','ready').encode())); "
              f"http.server.HTTPServer(('127.0.0.1',{port}),handler).serve_forever()")
    return {'execution': {'type': 'process', 'command': [sys.executable, '-c', script], 'workingDirectory': '.'},
            'dependencies': list(dependencies),
            'endpoints': {'http': {'protocol': 'http', 'bind': {'host': '127.0.0.1', 'port': port},
                                   'addresses': {'host': {'host': '127.0.0.1', 'port': port, 'scheme': 'http'}}}},
            'readiness': {'type': 'http', 'endpoint': 'http', 'path': '/', 'timeoutSeconds': 3}}


def fixture(root):
    dep = process_variant(free_port(), delay=0.2)
    main = process_variant(free_port(), ['dependency'])
    main['env'] = {'PROBE_VALUE': 'injected value'}
    data = {'schemaVersion': '1.0', 'nodes': [
        {'id': 'main', 'kind': 'application', 'variants': {'local': main}},
        {'id': 'dependency', 'kind': 'infrastructure', 'variants': {'local': dep}}],
        'profiles': {'dummy': {'targets': ['main'], 'selections': {'main': 'local', 'dependency': 'local'}}}}
    write_registry(root, data)
    return data


def write_registry(root, data):
    (root / 'registry.json').write_text(json.dumps(data), encoding='utf-8')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = fixture(self.root)

    def tearDown(self):
        stop(self.root)
        self.temporary.cleanup()

    def test_transitive_shared_dependency_order_and_injection(self):
        from urllib.request import ProxyHandler, build_opener
        middle = process_variant(free_port(), ['dependency'])
        self.data['nodes'].append({'id': 'middle', 'kind': 'application', 'variants': {'local': middle}})
        self.data['profiles']['dummy']['selections']['middle'] = 'local'
        self.data['nodes'][0]['variants']['local']['dependencies'] = ['middle', 'dependency']
        write_registry(self.root, self.data)
        events = []
        result = prepare(self.root, 'main', mode='dummy', emit=events.append)
        self.assertEqual(result['order'], ['dependency', 'middle', 'main'])
        self.assertEqual([e['node'] for e in events if e['phase'] == 'ready'], result['order'])
        port = self.data['nodes'][0]['variants']['local']['endpoints']['http']['bind']['port']
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/') as response:
            self.assertEqual(response.read(), b'injected value')
        manifest = (self.root / '.local/injector/session.json').read_text()
        self.assertNotIn('injected value', manifest)
        ids = [resource['pid'] for resource in json.loads(manifest)['resources']]
        stop(self.root)
        self.assertTrue(all(not psutil.pid_exists(pid) for pid in ids))

    def test_timeout_rolls_back_and_never_starts_dependent(self):
        dep = self.data['nodes'][1]['variants']['local']
        dep['execution']['command'] = [sys.executable, '-c', 'import time; time.sleep(60)']
        dep['readiness']['timeoutSeconds'] = 0.3
        write_registry(self.root, self.data)
        events = []
        with self.assertRaisesRegex(RegistryError, 'timed out'):
            prepare(self.root, 'main', mode='dummy', emit=events.append)
        self.assertFalse(any(e.get('node') == 'main' for e in events))
        self.assertFalse((self.root / '.local/injector/session.json').exists())

    def test_early_exit_is_failure(self):
        self.data['nodes'][1]['variants']['local']['execution']['command'] = [sys.executable, '-c', 'raise SystemExit(3)']
        write_registry(self.root, self.data)
        with self.assertRaisesRegex(RegistryError, 'exited'):
            prepare(self.root, 'main', mode='dummy')

    def test_preflight_checks_all_commands_before_starting(self):
        self.data['nodes'][0]['variants']['local']['execution']['command'] = ['nonexistent-injector-test-command']
        write_registry(self.root, self.data)
        events = []
        with self.assertRaisesRegex(RegistryError, 'unavailable'):
            prepare(self.root, 'main', mode='dummy', emit=events.append)
        self.assertEqual(events, [])

    def test_busy_port_does_not_touch_foreign_listener(self):
        port = self.data['nodes'][1]['variants']['local']['endpoints']['http']['bind']['port']
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port))
            listener.listen()
            with self.assertRaisesRegex(RegistryError, 'already in use'):
                prepare(self.root, 'main', mode='dummy')
            self.assertEqual(listener.getsockname()[1], port)

    def test_intellij_target_ready_after_dependencies(self):
        main = self.data['nodes'][0]['variants']['local']
        app = self.root / 'apps' / 'example app'
        app.mkdir(parents=True)
        main['execution'] = {'type': 'intellij', 'projectPath': r'apps\example app', 'module': 'probe', 'mainClass': 'example.Main'}
        dependency = self.data['nodes'][1]['variants']['local']
        dependency['execution']['workingDirectory'] = r'apps\example app'
        main['vmProperties'] = {'probe.value': 'hello world'}
        write_registry(self.root, self.data)
        events = []
        result = prepare(self.root, 'main', mode='dummy', emit=events.append)
        run_path = Path(result['runConfiguration'])
        self.assertEqual(run_path.parent, app.resolve() / '.run')
        self.assertTrue(run_path.is_file())
        self.assertLess(next(i for i,e in enumerate(events) if e.get('phase') == 'ready'),
                        next(i for i,e in enumerate(events) if e.get('phase') == 'debug-ready'))
        self.assertIn('probe.value=hello world', Path(result['runConfiguration']).read_text())

    def test_plain_intellij_preserves_explicit_spring_location(self):
        main = self.data['nodes'][0]['variants']['local']
        main['execution'] = {'type': 'intellij', 'projectPath': '.', 'module': 'probe', 'mainClass': 'example.Main'}
        main['vmProperties'] = {'spring.config.additional-location': 'file:./local-config/'}
        write_registry(self.root, self.data)
        result = prepare(self.root, 'main', mode='dummy')
        self.assertIn('file:./local-config/', Path(result['runConfiguration']).read_text())

    def test_reprepare_stops_previous_owned_processes(self):
        prepare(self.root, 'main', mode='dummy')
        old = json.loads((self.root / '.local/injector/session.json').read_text())
        prepare(self.root, 'main', mode='dummy')
        self.assertTrue(all(not psutil.pid_exists(r['pid']) for r in old['resources']))

    def test_pid_reuse_guard(self):
        directory = self.root / '.local/injector'
        directory.mkdir(parents=True)
        manifest = directory / 'session.json'
        manifest.write_text(json.dumps({'id': 'test', 'resources': [
            {'node': 'foreign', 'type': 'process', 'pid': os.getpid(), 'created': 0}]}))
        try:
            with self.assertRaisesRegex(RegistryError, 'identity changed'):
                stop(self.root)
        finally:
            manifest.unlink()

    def test_mode_ambiguity_requires_profile(self):
        self.data['profiles']['mock'] = self.data['profiles']['dummy']
        write_registry(self.root, self.data)
        with self.assertRaisesRegex(RegistryError, 'exactly one'):
            select_plan(self.root, 'main', mode='dummy')
        self.assertEqual(select_plan(self.root, 'main', profile='dummy')[1]['targets'], ['main'])

    def test_project_lock_rejects_concurrent_mutations(self):
        with _lock(_directory(self.root)):
            with self.assertRaisesRegex(RegistryError, 'another prepare or stop'):
                prepare(self.root, 'main', mode='dummy')


if __name__ == '__main__':
    unittest.main()
