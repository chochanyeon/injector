import json
import os
from pathlib import Path
import shlex
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import psutil

from injector_core.registry import RegistryError, runtime_directory
from injector_core.runtime import _directory, _lock, check_requirements, prepare, select_plan, stop


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

    def test_compose_dependencies_and_environment_are_checked_before_start(self):
        for node in self.data['nodes']:
            variant = node['variants']['local']
            variant['execution'] = {'type': 'compose', 'file': 'compose.yaml',
                                    'projectName': 'test', 'service': node['id']}
            variant['readiness'] = {'type': 'compose', 'timeoutSeconds': 3}
        self.data['nodes'][0]['variants']['local']['env'] = {'IMAGE': 'redis:7', 'PROBE_VALUE': 'literal ${KEEP}'}
        (self.root / 'compose.yaml').touch()
        write_registry(self.root, self.data)
        healthcheck = {'test': ['CMD', 'redis-cli', 'ping']}
        services = {
            'main': {'healthcheck': healthcheck, 'depends_on': {'database': {'required': True}}},
            'dependency': {'healthcheck': healthcheck},
        }
        with patch('injector_core.runtime._docker', return_value=json.dumps({'services': services})) as docker:
            with self.assertRaisesRegex(RegistryError, 'main: required Compose service database'):
                check_requirements(self.root, 'main', 'dummy')
            with self.assertRaisesRegex(RegistryError, 'main: required Compose service database'):
                prepare(self.root, 'main', 'dummy')
            self.assertTrue(all('up' not in call.args[0] for call in docker.call_args_list))
            self.assertFalse((runtime_directory(self.root) / 'session.json').exists())

        services['main']['depends_on'] = {'dependency': {'required': True}, 'database': {'required': False}}
        with patch('injector_core.runtime._docker', return_value=json.dumps({'services': services})) as docker, \
                patch('injector_core.runtime._containers', side_effect=[[], ['dep-id'], [], ['main-id']]), \
                patch('injector_core.runtime._occupied', return_value=None), patch('injector_core.runtime._wait'):
            try:
                self.assertEqual(prepare(self.root, 'main', 'dummy')['status'], 'ready')
                config_calls = [call for call in docker.call_args_list if 'config' in call.args[0]]
                up_calls = [call for call in docker.call_args_list if 'up' in call.args[0]]
                self.assertEqual(len(config_calls), 2)
                self.assertEqual(len(up_calls), 2)
                self.assertEqual(config_calls[-1].kwargs['env'], up_calls[-1].kwargs['env'])
                self.assertEqual(up_calls[-1].kwargs['env']['IMAGE'], 'redis:7')
                override = json.loads((runtime_directory(self.root) / 'compose-main.json').read_bytes())
                self.assertEqual(override['services']['main']['environment'],
                                 {'IMAGE': '${IMAGE?}', 'PROBE_VALUE': '${PROBE_VALUE?}'})
            finally:
                with patch('injector_core.runtime._containers', return_value=[]):
                    stop(self.root)

    def test_mixed_variants_start_only_selected_dependencies_and_inject_their_addresses(self):
        from urllib.request import ProxyHandler, build_opener

        main = self.data['nodes'][0]['variants']['local']
        main['env'] = {}
        main['dependencies'] = ['catalog', 'payment']
        main['injections'] = [{
            'channel': 'environment', 'key': 'PROBE_VALUE',
            'source': {'node': 'payment', 'endpoint': 'http', 'context': 'host', 'component': 'url'},
        }]
        ports = set(node['variants']['local']['endpoints']['http']['bind']['port'] for node in self.data['nodes'])

        def variant(*dependencies):
            port = free_port()
            while port in ports:
                port = free_port()
            ports.add(port)
            return process_variant(port, dependencies)

        self.data['nodes'].extend([
            {'id': 'catalog', 'kind': 'application',
             'variants': {'real': variant('dependency'), 'mock': variant()}},
            {'id': 'payment', 'kind': 'application',
             'variants': {'real': variant('dependency', 'database'), 'mock': variant()}},
            {'id': 'database', 'kind': 'infrastructure', 'variants': {'local': variant()}},
        ])
        self.data['profiles']['dummy']['selections'].update(catalog='real', payment='real', database='local')
        write_registry(self.root, self.data)
        original = (self.root / 'registry.json').read_bytes()
        _, real = select_plan(self.root, 'main', 'dummy')
        _, mock = select_plan(self.root, 'main', 'dummy', variants={'catalog': 'mock', 'payment': 'mock'})
        self.assertEqual(real['order'], ['dependency', 'catalog', 'database', 'payment', 'main'])
        self.assertEqual(mock['order'], ['catalog', 'payment', 'main'])
        with self.assertRaisesRegex(RegistryError, 'unknown variant'):
            prepare(self.root, 'main', 'dummy', variants={'payment': 'missing'})
        self.assertFalse((self.root / '.local/injector/session.json').exists())

        main_port = main['endpoints']['http']['bind']['port']
        payment = self.data['nodes'][3]
        for variants, expected, payment_variant in (
            ({}, real['order'], 'real'),
            ({'catalog': 'mock', 'payment': 'mock'}, mock['order'], 'mock'),
            ({'payment': 'mock'}, ['dependency', 'catalog', 'payment', 'main'], 'mock'),
        ):
            with self.subTest(variants=variants):
                events = []
                result = prepare(self.root, 'main', 'dummy', variants=variants, emit=events.append)
                self.assertEqual(result['order'], expected)
                self.assertEqual([event['node'] for event in events if event['phase'] == 'ready'], expected)
                port = payment['variants'][payment_variant]['endpoints']['http']['bind']['port']
                with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{main_port}/') as response:
                    self.assertEqual(response.read().decode(), f'http://127.0.0.1:{port}/')
        self.assertEqual((self.root / 'registry.json').read_bytes(), original)

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

    def test_launcher_exit_cleans_up_child_process(self):
        pid_file = self.root / 'child.pid'
        script = ('import pathlib,subprocess,sys; '
                  'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                  f'pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))')
        self.data['nodes'][1]['variants']['local']['execution']['command'] = [sys.executable, '-c', script]
        write_registry(self.root, self.data)
        with self.assertRaisesRegex(RegistryError, 'exited'):
            prepare(self.root, 'main', mode='dummy')
        try:
            child = psutil.Process(int(pid_file.read_text()))
        except psutil.NoSuchProcess:
            return
        try:
            child.wait(timeout=3)
        finally:
            if child.is_running():
                child.kill()

    def test_preflight_checks_all_commands_before_starting(self):
        self.data['nodes'][0]['variants']['local']['execution']['command'] = ['nonexistent-injector-test-command']
        write_registry(self.root, self.data)
        events = []
        with self.assertRaisesRegex(RegistryError, 'unavailable'):
            prepare(self.root, 'main', mode='dummy', emit=events.append)
        self.assertEqual(events, [])

    def test_relative_executable_is_resolved_from_working_directory(self):
        working = self.root / 'module with spaces'
        working.mkdir()
        dependency = self.data['nodes'][1]['variants']['local']
        (working / 'worker.py').write_text(dependency['execution']['command'][2], encoding='utf-8')
        if os.name == 'nt':
            launcher = working / 'launch.cmd'
            launcher.write_text(f'@"{sys.executable}" worker.py\n', encoding='utf-8')
        else:
            launcher = working / 'launch.sh'
            launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} worker.py\n', encoding='utf-8')
            launcher.chmod(0o755)
        dependency['execution'].update(command=['./' + launcher.name], workingDirectory=working.name)
        dependency['env'] = {'PATH': '.'}
        write_registry(self.root, self.data)
        self.assertEqual(prepare(self.root, 'main', mode='dummy')['status'], 'ready')
        dependency['execution']['command'] = [launcher.stem if os.name == 'nt' else launcher.name]
        write_registry(self.root, self.data)
        self.assertEqual(prepare(self.root, 'main', mode='dummy')['status'], 'ready')

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

    def test_external_registry_keeps_setup_artifacts_out_of_the_worktree(self):
        storage = self.root / 'registry library'
        storage.mkdir()
        worktree = self.root / 'worktree'
        module = worktree / 'app'
        module.mkdir(parents=True)
        main = self.data['nodes'].pop(0)
        variant = main['variants']['local']
        variant['execution'] = {'type': 'intellij', 'projectPath': 'app', 'module': 'probe',
                                'mainClass': 'example.Main'}
        variant['springProperties'] = {'demo.message': 'external registry'}
        self.data['schemaVersion'] = '1.1'
        self.data['nodeFiles'] = ['main.json']
        (storage / 'main.json').write_text(json.dumps(main), encoding='utf-8')
        write_registry(storage, self.data)
        registry = storage / 'my registry.json'
        (storage / 'registry.json').rename(registry)
        directory = runtime_directory(worktree, registry)
        self.assertEqual(runtime_directory(worktree, storage), runtime_directory(worktree, storage / 'registry.json'))
        self.assertNotEqual(directory, runtime_directory(worktree, storage))
        self.assertNotEqual(directory, runtime_directory(self.root, storage))
        try:
            result = prepare(worktree, 'main', 'dummy', registry=registry)
            self.assertTrue(result['externalRunConfiguration'])
            self.assertTrue(Path(result['runConfiguration']).is_relative_to(directory))
            self.assertTrue((directory / 'dummy/main/spring-overrides.yml').is_file())
            self.assertTrue((directory / 'session.json').is_file())
        finally:
            stop(worktree, registry=registry)
        self.assertFalse((directory / 'session.json').exists())
        self.assertEqual(list(worktree.iterdir()), [module])
        self.assertFalse(list(module.iterdir()))

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

    def test_reprepare_with_foreign_port_preserves_session_and_ide_settings(self):
        main = self.data['nodes'][0]['variants']['local']
        main['execution'] = {'type': 'intellij', 'projectPath': '.', 'module': 'probe', 'mainClass': 'example.Main'}
        write_registry(self.root, self.data)
        config = Path(prepare(self.root, 'main', mode='dummy')['runConfiguration'])
        session = self.root / '.local/injector/session.json'
        old_session, old_config = session.read_bytes(), config.read_bytes()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.data['nodes'][1]['variants']['local'] = process_variant(listener.getsockname()[1])
            main['env']['PROBE_VALUE'] = 'must not be published'
            write_registry(self.root, self.data)
            with self.assertRaisesRegex(RegistryError, 'already in use'):
                prepare(self.root, 'main', mode='dummy')
        self.assertEqual(session.read_bytes(), old_session)
        self.assertEqual(config.read_bytes(), old_config)
        self.assertTrue(all(psutil.pid_exists(resource['pid']) for resource in json.loads(old_session)['resources']))

    def test_failed_start_does_not_publish_ide_settings(self):
        self.data['schemaVersion'] = '1.1'
        main = self.data['nodes'][0]['variants']['local']
        main['execution'] = {'type': 'intellij', 'projectPath': '.', 'module': 'probe', 'mainClass': 'example.Main'}
        main['springProperties'] = {'demo.message': 'original value'}
        write_registry(self.root, self.data)
        config = Path(prepare(self.root, 'main', mode='dummy')['runConfiguration'])
        spring = self.root / '.local/injector/dummy/main/spring-overrides.yml'
        old_config = config.read_bytes()
        old_spring = spring.read_bytes()
        main['env']['PROBE_VALUE'] = 'must not be published'
        main['springProperties']['demo.message'] = 'replacement value'
        dependency = self.data['nodes'][1]['variants']['local']
        dependency['execution']['command'] = [sys.executable, '-c', 'raise SystemExit(3)']
        write_registry(self.root, self.data)
        with self.assertRaisesRegex(RegistryError, 'exited'):
            prepare(self.root, 'main', mode='dummy')
        self.assertEqual(config.read_bytes(), old_config)
        self.assertEqual(spring.read_bytes(), old_spring)

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
