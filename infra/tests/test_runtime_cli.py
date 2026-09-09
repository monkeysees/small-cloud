"""Operator CLI refusal checks; rendered policy is not live packet-filter evidence."""
from contextlib import ExitStack
import builtins
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'runtime' / 'sandbox.py'
SPEC = importlib.util.spec_from_file_location('runtime_cli', SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
IMAGE = 'sha256:' + 'a' * 64


class RuntimeCLI(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / 'runtime.json'
        self.settings = {'control_private_ip': '10.42.0.2', 'database_private_ip': '10.42.0.2',
                         'runtime_private_ip': '10.42.0.3', 'management_public_ips': ['8.8.8.8']}
        self.config.write_text(json.dumps(self.settings))

    def render(self):
        self.config.write_text(json.dumps(self.settings))
        return subprocess.run([sys.executable, str(SCRIPT), '--config', str(self.config), 'policy'],
                              text=True, capture_output=True, timeout=10)

    def test_policy_exposes_denial_and_narrow_database_ingress_exceptions(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = result.stdout
        for denied in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16',
                       '127.0.0.0/8', '100.64.0.0/10'):
            self.assertIn(denied, rules)
        for rule in ('iifname "sc-*" meta nfproto ipv6 drop',
                     'oifname "sc-*" meta nfproto ipv6 drop',
                     'iifname "sc-*" oifname "sc-*" drop',
                     'ip daddr { 8.8.8.8 } drop',
                     'ip daddr 10.42.0.2 tcp dport 5432 accept',
                     'ip saddr 10.42.0.2 tcp dport 8080 accept'):
            self.assertIn(rule, rules)
        self.assertLess(rules.index('ip daddr { 8.8.8.8 } drop'), rules.index('tcp dport 5432 accept'))
        self.assertLess(rules.index('tcp dport 5432 accept'), rules.index('10.0.0.0/8'))

    def test_missing_management_inventory_and_ipv6_addresses_are_refused(self):
        for changes in ({'management_public_ips': []}, {'management_public_ips': ['::1']},
                        {'database_private_ip': '10.42.0.2; accept'}, {'runtime_private_ip': '::1'}):
            with self.subTest(changes=changes):
                before = self.settings.copy()
                self.settings.update(changes)
                result = self.render()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.settings = before

    def invoke_start(self, tool='tool-a', image=IMAGE, entries=(), extra=(), network=None, resume=False):
        calls = []
        def process(argv, **kwargs):
            argv = list(argv)
            calls.append(argv)
            if argv[:3] == ['docker', 'ps', '-aq']:
                return subprocess.CompletedProcess(argv, 0, '\n'.join(str(index) for index in range(len(entries))))
            if argv[:2] == ['docker', 'inspect']:
                return subprocess.CompletedProcess(argv, 0, json.dumps(entries))
            if network is not None:
                if argv[:3] == ['docker', 'image', 'inspect']:
                    return subprocess.CompletedProcess(argv, 0, json.dumps([{'Config': {'Cmd': ['app'], 'Entrypoint': []}}]))
                if argv[:3] == ['docker', 'network', 'inspect']:
                    return subprocess.CompletedProcess(argv, 0, json.dumps([network]))
                if argv[:2] == ['docker', 'commit']:
                    return subprocess.CompletedProcess(argv, 0, 'sha256:' + 'b' * 64)
                if argv[0] in ('docker', 'nft'):
                    return subprocess.CompletedProcess(argv, 0, 'fixture-container')
            raise AssertionError(f'unexpected mutating process: {argv}')
        original_open = builtins.open
        def open_boundary(path, *args, **kwargs):
            if path == '/run/small-cloud-runtime.lock':
                path = self.root / 'lock'
            return original_open(path, *args, **kwargs)
        arguments = ['resume', tool, 'd-' + 'a' * 24] if resume else ['start', tool, image]
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['sandbox', '--config', str(self.config),
                *arguments, *extra]))
            if resume:
                environment = self.root / 'environment'
                environment.write_text('DATABASE_URL=fixture\n')
                environment.chmod(0o600)
                original_lstat = Path.lstat
                def lstat(path, *args, **kwargs):
                    info = original_lstat(path, *args, **kwargs)
                    if path == environment:
                        values = list(info)
                        values[4] = 0
                        return __import__('os').stat_result(values)
                    return info
                stack.enter_context(patch.object(Path, 'lstat', lstat))
            stack.enter_context(patch.object(runtime.os, 'geteuid', return_value=0))
            stack.enter_context(patch.object(runtime, 'IMAGE_STATE', self.root / 'runtime' / 'images'))
            stack.enter_context(patch.object(runtime, 'RESOLVER_FILE', self.root / 'resolv.conf'))
            stack.enter_context(patch.object(Path, 'read_bytes', return_value=b'-----BEGIN CERTIFICATE-----\nfixture'))
            stack.enter_context(patch.object(builtins, 'open', side_effect=open_boundary))
            stack.enter_context(patch.object(runtime.subprocess, 'run', side_effect=process))
            runtime.main()
        return calls

    def test_resume_uses_retained_image_and_the_same_capacity_boundary(self):
        state = self.root / 'runtime'
        state.mkdir(mode=0o700)
        releases = state / 'releases.json'
        releases.write_text(json.dumps({'tool-a/d-' + 'a' * 24: IMAGE}))
        releases.chmod(0o600)
        network = {'Driver': 'bridge', 'EnableIPv6': False, 'Containers': {},
                   'Options': {'com.docker.network.bridge.name': 'sc-0'},
                   'IPAM': {'Config': [{'Subnet': '172.30.0.0/24', 'Gateway': '172.30.0.1', 'IPRange': ''}]}}
        calls = self.invoke_start(network=network, resume=True, extra=['--env-file', str(self.root / 'environment')])
        self.assertIn(['docker', 'start', 'sc-tool-a-active'], calls)
        self.assertIn(['docker', 'image', 'inspect', IMAGE], calls)
        entries = [{'Name': f'/sc-tool-{i}-active', 'Config': {'Labels': {'small-cloud.tool': f'tool-{i}',
                    'small-cloud.role': 'active', 'small-cloud.slot': str(i)}}} for i in range(5)]
        with self.assertRaises(runtime.ActiveCapacity):
            self.invoke_start(entries=entries, resume=True, extra=['--env-file', str(self.root / 'environment')])

    def test_docker29_empty_iprange_network_allows_launch(self):
        network = {'Driver': 'bridge', 'EnableIPv6': False, 'Containers': {},
                   'Options': {'com.docker.network.bridge.name': 'sc-0'},
                   'IPAM': {'Config': [{'Subnet': '172.30.0.0/24', 'Gateway': '172.30.0.1', 'IPRange': ''}]}}
        calls = self.invoke_start(network=network)
        self.assertIn(['docker', 'start', 'sc-tool-a-active'], calls)
        creation = next(call for call in calls if call[:3] == ['docker', 'create', '--name'])
        self.assertEqual(creation[creation.index('--mount') + 1],
                         f'type=bind,src={self.root / "resolv.conf"},dst=/etc/resolv.conf,readonly')
        self.assertEqual((self.root / 'resolv.conf').read_text(),
                         'nameserver 1.1.1.1\nnameserver 8.8.8.8\noptions timeout:2 attempts:2\n')

    def test_json_environment_uses_private_socket_preserving_values_and_runtime_limits(self):
        from http.server import BaseHTTPRequestHandler
        import socketserver
        import threading
        received = []
        response_status = [201]

        class DockerAPI(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(response_status[0])
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')

        path = str(self.root / 'docker.sock')
        server = socketserver.UnixStreamServer(path, DockerAPI)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        environment = self.root / 'environment.json'
        values = {'SERVICE_TOKEN': 'exact-token\n\n', 'LD_PRELOAD': 'app-only', 'DOCKER_HOST': 'app-only'}
        environment.write_text(json.dumps(values))
        environment.chmod(0o600)
        network = {'Driver': 'bridge', 'EnableIPv6': False, 'Containers': {},
                   'Options': {'com.docker.network.bridge.name': 'sc-0'},
                   'IPAM': {'Config': [{'Subnet': '172.30.0.0/24', 'Gateway': '172.30.0.1', 'IPRange': ''}]}}
        original_fstat = runtime.os.fstat

        def root_owned(fd):
            info = list(original_fstat(fd))
            info[4] = 0
            return runtime.os.stat_result(info)

        with patch.object(runtime, 'DOCKER_SOCKET', path), patch.object(runtime.os, 'fstat', side_effect=root_owned):
            calls = self.invoke_start(network=network, extra=['--env-json', str(environment),
                                                            '--deployment', 'd-' + 'a' * 24])
            self.assertNotIn('exact-token', str(calls))
            self.assertEqual(received[0]['Env'], ['SERVICE_TOKEN=exact-token\n\n', 'LD_PRELOAD=app-only',
                                                 'DOCKER_HOST=app-only', 'PORT=8080'])
            host = received[0]['HostConfig']
            self.assertEqual((host['Runtime'], host['Memory'], host['MemorySwap'], host['NanoCpus'], host['PidsLimit']),
                             ('runsc', 536870912, 536870912, 500000000, 128))
            self.assertTrue(host['ReadonlyRootfs'])
            self.assertEqual(host['CapDrop'], ['ALL'])
            self.assertEqual(host['LogConfig']['Config']['cache-disabled'], 'true')
            response_status[0] = 500
            self.root = self.root / 'failed-create'
            self.root.mkdir()
            with self.assertRaisesRegex(ValueError, '^Runtime container creation failed$'):
                self.invoke_start(network=network, extra=['--env-json', str(environment)])

    def test_prune_only_removes_tracked_aged_images_without_force(self):
        state = self.root / 'runtime' / 'images'
        state.parent.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        old = 'sha256:' + 'c' * 64
        fresh = 'sha256:' + 'd' * 64
        used = 'sha256:' + 'e' * 64
        for image, age in ((old, 90000), (fresh, 60), (used, 90000)):
            record = state / (image[7:] + '.json')
            record.write_text(json.dumps({'image': image, 'created_at': time.time() - age}))
            record.chmod(0o600)
        # Recovery must also handle an inventory already above the admission cap.
        for number in range(256):
            record = state / (f'{number:064x}' + '.json')
            record.write_text(json.dumps({'image': 'sha256:' + f'{number:064x}', 'created_at': time.time()}))
            record.chmod(0o600)
        calls = []
        def process(argv, **kwargs):
            calls.append(list(argv))
            if argv[-1] == used:
                raise subprocess.CalledProcessError(1, argv)
            return subprocess.CompletedProcess(argv, 0, '')
        original_open = builtins.open
        def open_boundary(path, *args, **kwargs):
            return original_open(self.root / 'lock' if path == '/run/small-cloud-runtime.lock' else path, *args, **kwargs)
        with patch.object(sys, 'argv', ['sandbox', '--config', str(self.config), 'prune-images']), \
                patch.object(runtime.os, 'geteuid', return_value=0), \
                patch.object(runtime, 'IMAGE_STATE', state), \
                patch.object(builtins, 'open', side_effect=open_boundary), \
                patch.object(runtime.subprocess, 'run', side_effect=process):
            runtime.main()
        self.assertEqual(sorted(calls), sorted([['docker', 'image', 'rm', '--no-prune', old], ['docker', 'image', 'rm', '--no-prune', used]]))
        self.assertFalse((state / (old[7:] + '.json')).exists())
        self.assertTrue((state / (fresh[7:] + '.json')).exists())
        self.assertTrue((state / (used[7:] + '.json')).exists())

    def test_full_image_inventory_refuses_preparation(self):
        state = self.root / 'runtime' / 'images'
        state.parent.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        for number in range(256):
            (state / f'{number:064x}.json').write_text('{}')
        network = {'Driver': 'bridge', 'EnableIPv6': False, 'Containers': {},
                   'Options': {'com.docker.network.bridge.name': 'sc-0'},
                   'IPAM': {'Config': [{'Subnet': '172.30.0.0/24', 'Gateway': '172.30.0.1', 'IPRange': ''}]}}
        with self.assertRaisesRegex(ValueError, 'prune before preparing'):
            self.invoke_start(network=network)

    def test_stored_release_survives_pruning_without_a_running_container(self):
        state = self.root / 'runtime' / 'images'
        original_open = builtins.open
        def open_boundary(path, *args, **kwargs):
            return original_open(self.root / 'lock' if path == '/run/small-cloud-runtime.lock' else path, *args, **kwargs)
        calls = []
        child = 'sha256:' + 'b' * 64
        present = {IMAGE, child}
        def process(argv, **kwargs):
            calls.append(list(argv))
            if list(argv[:3]) == ['docker', 'image', 'rm']:
                present.discard(argv[-1])
                if argv[-1] == child and '--no-prune' not in argv:
                    present.discard(IMAGE)
            return subprocess.CompletedProcess(argv, 0, json.dumps([{'Id': IMAGE}]))
        def invoke(*args):
            with patch.object(sys, 'argv', ['sandbox', '--config', str(self.config), *args]):
                runtime.main()
        with patch.object(runtime.os, 'geteuid', return_value=0), \
                patch.object(runtime, 'IMAGE_STATE', state), \
                patch.object(builtins, 'open', side_effect=open_boundary), \
                patch.object(runtime.subprocess, 'run', side_effect=process):
            invoke('retain-image', 'tool-a', 'release-a', IMAGE)
            record = state / (child[7:] + '.json')
            record.write_text(json.dumps({'image': child, 'created_at': time.time() - 90000}))
            record.chmod(0o600)
            with patch.object(runtime.time, 'time', return_value=time.time() + 90000):
                invoke('prune-images')
            self.assertIn(IMAGE, present, 'removing a derived image must preserve its pinned untagged parent')
            self.assertNotIn(child, present)
            self.assertIn(IMAGE, present)
            invoke('forget-release', 'tool-a', 'release-a')
            invoke('prune-images')
            self.assertIn(IMAGE, present)
            with patch.object(runtime.time, 'time', return_value=time.time() + 90000):
                invoke('prune-images')
            self.assertNotIn(IMAGE, present)

    def test_mutable_image_and_invalid_tool_names_are_refused_before_mutation(self):
        for tool, image in [('tool-a', 'alpine:latest'), ('../escape', IMAGE), ('UPPER', IMAGE)]:
            with self.subTest(tool=tool, image=image):
                with self.assertRaises(ValueError):
                    self.invoke_start(tool, image)

    def test_sixth_active_tool_and_orphan_candidate_are_refused(self):
        entries = [{'Name': f'/sc-tool-{i}-active', 'Config': {'Labels': {'small-cloud.tool': f'tool-{i}',
                    'small-cloud.role': 'active', 'small-cloud.slot': str(i)}}} for i in range(5)]
        with self.assertRaisesRegex(ValueError, 'five active'):
            self.invoke_start(entries=entries)
        with self.assertRaisesRegex(ValueError, 'exactly one existing active'):
            self.invoke_start(extra=['--candidate'])

    def test_unprotected_environment_is_refused_without_reading_values(self):
        env = self.root / 'tool.env'
        env.write_text('DATABASE_URL=fixture-secret\n')
        env.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'mode 0600') as error:
            self.invoke_start(extra=['--env-file', str(env)])
        self.assertNotIn('fixture-secret', str(error.exception))


if __name__ == '__main__':
    unittest.main()

class PromotionCLI(unittest.TestCase):
    setUp = RuntimeCLI.setUp

    def test_idle_stop_removes_only_own_allocation_and_keeps_retained_release(self):
        entry = {'Name': '/sc-app-a-active', 'Config': {'Labels': {'small-cloud.tool': 'app-a'}}}
        present = [entry]
        calls = []

        def process(argv, **kwargs):
            args = list(argv)
            calls.append(args)
            output = ''
            if args[:3] == ['docker', 'ps', '-aq']:
                output = 'app-a' if present else ''
            elif args[:2] == ['docker', 'inspect']:
                output = json.dumps(present)
            elif args[:3] == ['docker', 'rm', '-f']:
                self.assertEqual(args[3:], ['sc-app-a-active'])
                present.clear()
            else:
                self.fail('Idle stop attempted unrelated resource mutation: ' + repr(args))
            return subprocess.CompletedProcess(argv, 0, output)

        original_open = builtins.open
        def open_boundary(path, *args, **kwargs):
            return original_open(self.root / 'lock' if path == '/run/small-cloud-runtime.lock' else path, *args, **kwargs)

        with patch.object(sys, 'argv', ['sandbox', '--config', str(self.config), 'stop', 'app-a']), \
                patch.object(runtime.os, 'geteuid', return_value=0), \
                patch.object(builtins, 'open', side_effect=open_boundary), \
                patch.object(runtime.subprocess, 'run', side_effect=process):
            runtime.main()
            runtime.main()
        self.assertEqual(present, [])
        self.assertEqual(calls.count(['docker', 'rm', '-f', 'sc-app-a-active']), 1)

    def test_ready_candidate_is_promoted_without_recreating_its_process(self):
        entries = [
            {'Name': '/sc-app-a-active', 'State': {'Running': True},
             'Config': {'Labels': {'small-cloud.tool': 'app-a', 'small-cloud.role': 'active'}}},
            {'Name': '/sc-app-a-candidate', 'State': {'Running': True},
             'Config': {'Labels': {'small-cloud.tool': 'app-a', 'small-cloud.role': 'candidate'}}}]
        calls = []
        def process(argv, **kwargs):
            calls.append(list(argv))
            if list(argv[:3]) == ['docker', 'ps', '-aq']:
                return subprocess.CompletedProcess(argv, 0, 'old new')
            if list(argv[:2]) == ['docker', 'inspect']:
                return subprocess.CompletedProcess(argv, 0, json.dumps(entries))
            return subprocess.CompletedProcess(argv, 0, '')
        original_open = builtins.open
        def open_boundary(path, *args, **kwargs):
            return original_open(self.root / 'lock' if path == '/run/small-cloud-runtime.lock' else path, *args, **kwargs)
        with patch.object(sys, 'argv', ['sandbox', '--config', str(self.config), 'promote', 'app-a']), \
                patch.object(runtime.os, 'geteuid', return_value=0), \
                patch.object(builtins, 'open', side_effect=open_boundary), \
                patch.object(runtime.subprocess, 'run', side_effect=process):
            runtime.main()
        self.assertEqual(calls[-2:], [['docker', 'rm', '-f', 'sc-app-a-active'],
                                    ['docker', 'rename', 'sc-app-a-candidate', 'sc-app-a-active']])
        self.assertFalse(any(call[:2] == ['docker', 'create'] for call in calls))
