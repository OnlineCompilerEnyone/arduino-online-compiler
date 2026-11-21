#!/usr/bin/env python3

import base64
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('download_project', ROOT / 'scripts/download-project.py')
download_project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download_project)

INI = b'[env:test]\nplatform = atmelavr\nframework = arduino\nboard = uno\n'

FILES = {
    'platformio.ini': INI,
    'src/main.ino': b'void setup() {}\nvoid loop() {}\n',
    'include/a.h': b'header',
    'lib/example/lib.cpp': b'library',
    'data/index.html': b'data',
    'boards/custom.json': b'{}',
    'scripts/tool.py': b'print(1)',
    'test/test_example.cpp': b'test',
}


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def tar_bytes(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    routes = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/project.zip')
            self.end_headers()
            return
        if self.path == '/bad-redirect':
            self.send_response(302)
            self.send_header('Location', 'file:///etc/passwd')
            self.end_headers()
            return
        if self.path == '/large':
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(50 * 16):
                    self.wfile.write(b'x' * 65536)
                self.wfile.write(b'x')
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        content = self.routes.get(self.path)
        if content is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(content)


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.routes = {'/project.zip': zip_bytes(FILES), '/project.tar.gz': tar_bytes(FILES)}
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prepare(self, inputs):
        event = self.root / 'event.json'
        event.write_text(json.dumps({'inputs': inputs}), encoding='utf-8')
        workflow = (ROOT / '.github/workflows/pio-compile.yml').read_text(encoding='utf-8')
        step = workflow.split('      - name: Prepare project\n', 1)[1]
        script = step.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0]
        script = '\n'.join(line[10:] for line in script.splitlines())
        env = dict(os.environ, GITHUB_EVENT_PATH=str(event), GITHUB_WORKSPACE=str(self.root))
        return subprocess.run(
            ['bash', '-c', script],
            cwd=ROOT,
            env=env,
            text=True,
            encoding='utf-8',
            errors='replace',
            capture_output=True,
        )

    def test_complete_zip_tar_and_redirect(self):
        for endpoint in ('/project.zip', '/project.tar.gz', '/redirect'):
            with self.subTest(endpoint=endpoint), tempfile.TemporaryDirectory(dir=self.root) as temp:
                target = Path(temp) / 'project'
                archive = Path(temp) / 'archive'
                download_project.download(self.base_url + endpoint, archive)
                download_project.extract(archive, target)
                for name, content in FILES.items():
                    self.assertEqual((target / name).read_bytes(), content)
                self.assertFalse((target / 'src/main.cpp').exists())

    def test_workflow_prefers_url(self):
        result = self.prepare({
            'project_url': self.base_url + '/project.zip',
            'encoded_ini': 'invalid',
            'encoded_sketch': 'invalid',
            'artifact_password': 'password',
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'project/src/main.ino').read_bytes(), FILES['src/main.ino'])

    def test_url_failure_does_not_fall_back(self):
        url = self.base_url + '/missing?token=private'
        result = self.prepare({
            'project_url': url,
            'encoded_ini': base64.b64encode(INI).decode(),
            'encoded_sketch': base64.b64encode(b'valid').decode(),
            'artifact_password': 'password',
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HTTP 404', result.stderr)
        self.assertNotIn(url, result.stderr + result.stdout)
        self.assertFalse((self.root / 'project').exists())

    def test_base64_fallback_and_missing_inputs(self):
        inputs = {
            'encoded_ini': base64.b64encode(INI).decode(),
            'encoded_sketch': base64.b64encode(b'valid sketch').decode(),
            'artifact_password': 'password',
        }
        result = self.prepare(inputs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'project/src/main.cpp').read_bytes(), b'valid sketch')

        inputs['encoded_sketch'] = ''
        result = self.prepare(inputs)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing Base64 project inputs', result.stderr)

    def test_workflow_still_rejects_forbidden_ini(self):
        for index, value in enumerate((
            b'extra_scripts = scripts/a.py\n',
            b'platform_packages = package\n',
            b'lib_deps = https://example.com/library.zip\n',
        )):
            with self.subTest(value=value), tempfile.TemporaryDirectory(dir=self.root) as temp:
                Handler.routes[f'/unsafe-{index}.zip'] = zip_bytes({'platformio.ini': INI + value})
                previous = self.root
                self.root = Path(temp)
                try:
                    result = self.prepare({
                        'project_url': self.base_url + f'/unsafe-{index}.zip',
                        'artifact_password': 'password',
                    })
                finally:
                    self.root = previous
                self.assertNotEqual(result.returncode, 0)

    def test_rejects_unsafe_archives(self):
        link = zipfile.ZipInfo('src/link')
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        symlink = io.BytesIO()
        with zipfile.ZipFile(symlink, 'w') as archive:
            archive.writestr('platformio.ini', INI)
            archive.writestr(link, '../../outside')

        tar_link = io.BytesIO()
        with tarfile.open(fileobj=tar_link, mode='w:gz') as archive:
            info = tarfile.TarInfo('platformio.ini')
            info.size = len(INI)
            archive.addfile(info, io.BytesIO(INI))
            info = tarfile.TarInfo('link')
            info.type = tarfile.LNKTYPE
            info.linkname = 'platformio.ini'
            archive.addfile(info)

        cases = [
            zip_bytes({'platformio.ini': INI, '../escape': b'bad'}),
            zip_bytes({'platformio.ini': INI, 'C:/escape': b'bad'}),
            tar_bytes({'platformio.ini': INI, '/escape': b'bad'}),
            zip_bytes({'platformio.ini': INI, 'src': b'file', 'src/main.cpp': b'bad'}),
            zip_bytes({'wrapper/platformio.ini': INI}),
            symlink.getvalue(),
            tar_link.getvalue(),
        ]
        for index, content in enumerate(cases):
            with self.subTest(index=index):
                archive = self.root / f'bad-{index}'
                archive.write_bytes(content)
                with self.assertRaises(download_project.ProjectError):
                    download_project.extract(archive, self.root / f'project-{index}')
        self.assertFalse((self.root / 'escape').exists())

    def test_limits_and_invalid_protocol(self):
        archive = self.root / 'archive'
        with self.assertRaisesRegex(download_project.ProjectError, '50 MiB'):
            download_project.download(self.base_url + '/large', archive)
        with self.assertRaisesRegex(download_project.ProjectError, 'HTTP or HTTPS'):
            download_project.download('file:///etc/passwd', archive)
        with self.assertRaises(download_project.ProjectError):
            download_project.download(self.base_url + '/bad-redirect', archive)

        header = tarfile.TarInfo('large')
        header.size = 200 * 1024 * 1024 + 1
        archive.write_bytes(gzip.compress(header.tobuf()))
        with self.assertRaisesRegex(download_project.ProjectError, '200 MiB'):
            download_project.extract(archive, self.root / 'project')

        archive.write_bytes(zip_bytes({'platformio.ini': INI, 'large': b'1234'}))
        with patch.object(download_project, 'MAX_EXTRACTED', len(INI) + 3):
            with self.assertRaisesRegex(download_project.ProjectError, '200 MiB'):
                download_project.extract(archive, self.root / 'project')
        with patch.object(download_project, 'MAX_EXTRACTED', len(INI) + 4):
            download_project.extract(archive, self.root / 'project')


if __name__ == '__main__':
    unittest.main()
