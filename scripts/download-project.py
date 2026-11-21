#!/usr/bin/env python3
"""Download and safely extract a complete PlatformIO project."""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

MAX_DOWNLOAD = 50 * 1024 * 1024
MAX_EXTRACTED = 200 * 1024 * 1024
MAX_ENTRIES = 10000
DOWNLOAD_TIMEOUT = 120
CHUNK_SIZE = 64 * 1024


class ProjectError(Exception):
    pass


def check_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = parsed.scheme in ('http', 'https') and parsed.hostname
    except ValueError:
        valid = False
    if not valid:
        raise ProjectError('Project URL must use HTTP or HTTPS')
    if parsed.username or parsed.password:
        raise ProjectError('Project URL must not contain credentials')


class HttpRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, archive):
    check_url(url)
    opener = urllib.request.build_opener(HttpRedirectHandler())
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    try:
        with opener.open(url, timeout=30) as response, archive.open('wb') as output:
            total = 0
            while True:
                if time.monotonic() > deadline:
                    raise ProjectError('Project download timed out')
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise ProjectError('Project download exceeds 50 MiB')
                output.write(chunk)
    except urllib.error.HTTPError as error:
        raise ProjectError(f'Project download failed (HTTP {error.code})') from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ProjectError('Project download failed') from None


def member_path(name):
    if not name or '\x00' in name or '\\' in name or PureWindowsPath(name).is_absolute() or name.startswith('/'):
        raise ProjectError('Archive contains an invalid path')
    parts = name.split('/')
    if '..' in parts:
        raise ProjectError('Archive contains an invalid path')
    path = PurePosixPath(name)
    if not path.parts:
        return None
    return path


def extract(archive, project):
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as source:
                entries = []
                for item in source.infolist():
                    mode = item.external_attr >> 16
                    file_type = stat.S_IFMT(mode)
                    if item.flag_bits & 1 or file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise ProjectError('Archive contains an unsupported file type')
                    is_dir = item.is_dir()
                    if (file_type == stat.S_IFDIR and not is_dir) or (
                        file_type == stat.S_IFREG and is_dir
                    ):
                        raise ProjectError('Archive contains an invalid directory')
                    entries.append((item.filename, is_dir, item.file_size, mode, item))
                extract_entries(entries, source.open, project)
        else:
            with tarfile.open(archive, 'r:gz') as source:
                entries = []
                declared_size = 0
                for item in source:
                    if not (item.isfile() or item.isdir()):
                        raise ProjectError('Archive contains an unsupported file type')
                    entries.append((item.name, item.isdir(), item.size, item.mode, item))
                    if len(entries) > MAX_ENTRIES:
                        raise ProjectError('Archive contains too many entries')
                    declared_size += item.size
                    if declared_size > MAX_EXTRACTED:
                        raise ProjectError('Extracted project exceeds 200 MiB')
                extract_entries(entries, source.extractfile, project)
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, OSError, RuntimeError):
        raise ProjectError('Project archive could not be extracted') from None


def extract_entries(entries, open_member, project):
    if len(entries) > MAX_ENTRIES:
        raise ProjectError('Archive contains too many entries')

    files = set()
    directories = set()
    declared_size = 0
    prepared = []

    for name, is_dir, size, mode, item in entries:
        path = member_path(name)
        if path is None:
            if not is_dir:
                raise ProjectError('Archive contains an invalid path')
            continue
        if path in files or (not is_dir and path in directories):
            raise ProjectError('Archive contains conflicting paths')
        if any(parent in files for parent in path.parents):
            raise ProjectError('Archive contains conflicting paths')
        if is_dir:
            directories.add(path)
        else:
            files.add(path)
            declared_size += size
            if declared_size > MAX_EXTRACTED:
                raise ProjectError('Extracted project exceeds 200 MiB')
        directories.update(parent for parent in path.parents if parent != PurePosixPath('.'))
        prepared.append((path, is_dir, size, mode, item))

    if PurePosixPath('platformio.ini') not in files:
        raise ProjectError('Archive root must contain platformio.ini')

    project.mkdir(parents=True, exist_ok=False)

    total = 0
    for path, is_dir, size, mode, item in prepared:
        destination = project.joinpath(*path.parts)
        if is_dir:
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open_member(item) as source, destination.open('xb') as output:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                total += len(chunk)
                if written > size or total > MAX_EXTRACTED:
                    raise ProjectError('Extracted project exceeds its declared size or 200 MiB')
                output.write(chunk)
        if written != size:
            raise ProjectError('Archive file size does not match its contents')
        os.chmod(destination, 0o755 if mode & 0o111 else 0o644)


def main():
    if len(sys.argv) != 2:
        print('Usage: download-project.py PROJECT_DIR (URL on stdin)', file=sys.stderr)
        return 2

    try:
        url = sys.stdin.read().strip()
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / 'project-archive'
            download(url, archive)
            extract(archive, Path(sys.argv[1]))
    except ProjectError as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
