"""Validate and package local source without invoking Docker."""
import io
import os
from pathlib import Path
import posixpath
import re
import stat
import tarfile
from typing import NoReturn

from .common import Failure

LIMIT = 100 * 1024 * 1024


def unchanged(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def docker_pattern(pattern):
    # Moby treats a leading ** plus a literal tail as a suffix match.
    if pattern.startswith('**') and not any(char in pattern[2:] for char in '*?[]\\'):
        suffix = re.escape(pattern[2:])
        expression = '.*' + suffix
        if pattern[2:].startswith('/'):
            expression += '|' + re.escape(pattern[3:])
        return re.compile('(?:' + expression + r')\Z')
    expression, index = '', 0
    while index < len(pattern):
        char = pattern[index]
        if char == '*':
            if pattern[index:index + 2] == '**':
                index += 1
                if pattern[index + 1:index + 2] == '/':
                    index += 1
                expression += '.*' if index + 1 == len(pattern) else '(?:.*/)?'
            else:
                expression += '[^/]*'
        elif char == '?':
            expression += '[^/]'
        elif char == '[':
            end = pattern.find(']', index + 1)
            if end < 0:
                raise Failure('UPLOAD_REJECTED', 'Invalid .dockerignore character class.')
            expression += '(?!/)' + pattern[index:end + 1]
            index = end
        elif char == '\\':
            index += 1
            if index == len(pattern):
                raise Failure('UPLOAD_REJECTED', 'Invalid .dockerignore escape.')
            expression += re.escape(pattern[index])
        else:
            expression += re.escape(char)
        index += 1
    try:
        return re.compile(expression + r'\Z')
    except re.error:
        raise Failure('UPLOAD_REJECTED', 'Invalid .dockerignore pattern.') from None


def platform_path(parts):
    return any(parts[i:i + 2] == ('.config', 'small-cloud')
               or parts[i:i + 3] == ('.local', 'state', 'small-cloud')
               for i in range(len(parts)))


def mandatory_path(parts):
    return any(name in ('.git', '.small-cloud', '.env') or name.startswith('.env.')
               for name in parts)


def reject(message) -> NoReturn:
    raise Failure('UPLOAD_REJECTED', message)


def validate_archive(data: bytes):
    """Validate the untrusted wire archive independently of CLI packaging."""
    if len(data) > LIMIT + 16 * 1024 * 1024:
        reject('Archive exceeds upload bound.')
    seen, files, total = set(), set(), 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r|') as archive:
            for count, member in enumerate(archive, 1):
                name = member.name
                parts = tuple(name.split('/'))
                if (count > 10000 or not name or name.startswith('/')
                        or any(part in ('', '.', '..') for part in parts)
                        or name in seen or not (member.isfile() or member.isdir())
                        or member.size < 0 or (member.isdir() and member.size)
                        or mandatory_path(parts) or platform_path(parts)
                        or any('/'.join(parts[:i]) in files for i in range(1, len(parts)))
                        or (member.isfile() and any(other.startswith(name + '/') for other in seen))):
                    reject('Unsafe source archive.')
                seen.add(name)
                total += member.size
                if total > LIMIT:
                    reject('Source exceeds 100 MiB.')
                if member.isfile():
                    files.add(name)
                    stream = archive.extractfile(member)
                    if stream is None:
                        reject('Archive file has no readable content.')
                    with stream:
                        remaining = member.size
                        while remaining:
                            chunk = stream.read(min(65536, remaining))
                            if not chunk:
                                reject('Incomplete source archive.')
                            remaining -= len(chunk)
    except (tarfile.TarError, OSError, ValueError, EOFError):
        reject('Invalid source archive.')
    if 'Dockerfile' not in files:
        reject('A root Dockerfile is required.')


def package(folder):
    try:
        return _package(folder)
    except (OSError, UnicodeError, ValueError, tarfile.TarError):
        reject('Source could not be safely read or changed during packaging.')


def _package(folder):
    root = Path(folder).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        reject('Source paths must not contain symlinks.')
    root = root.resolve(strict=True)
    protected = [Path(os.environ.get(variable, str(Path.home() / default))) / 'small-cloud'
                 for variable, default in [('XDG_CONFIG_HOME', '.config'), ('XDG_STATE_HOME', '.local/state')]]
    protected_ids = set()
    for directory in protected:
        directory = directory.resolve()
        if root.is_relative_to(directory) or directory.is_relative_to(root):
            reject('Source overlaps platform configuration or credential storage.')
        if directory.exists():
            info = directory.stat()
            protected_ids.add((info.st_dev, info.st_ino))
    patterns = []
    included, excluded, total = [], [], 0
    archive = io.BytesIO()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    # Pin every ancestor to a directory handle to prevent path substitution.
    root_fd = os.open('/', directory_flags)
    try:
        for component in root.parts[1:]:
            child = os.open(component, directory_flags, dir_fd=root_fd)
            os.close(root_fd)
            root_fd = child
        root_info = os.fstat(root_fd)
        if (root_info.st_dev, root_info.st_ino) in protected_ids:
            reject('Source overlaps platform configuration or credential storage.')
        if unchanged(root.stat()) != unchanged(root_info):
            reject('Source changed during packaging.')
        try:
            ignore_info = os.stat('.dockerignore', dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            ignore_info = None
        if ignore_info is not None:
            if not stat.S_ISREG(ignore_info.st_mode) or ignore_info.st_nlink != 1 or ignore_info.st_size > LIMIT:
                reject('Unsafe .dockerignore file.')
            fd = os.open('.dockerignore', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
            with os.fdopen(fd, 'rb') as stream:
                if unchanged(os.fstat(fd)) != unchanged(ignore_info):
                    reject('Source changed during packaging.')
                ignore_data = stream.read(LIMIT + 1)
                if unchanged(os.fstat(fd)) != unchanged(ignore_info):
                    reject('Source changed during packaging.')
            for line in ignore_data.decode('utf-8-sig').splitlines():
                if line.startswith('#') or not line.strip():
                    continue
                value = line.strip()
                negate = value.startswith('!')
                value = value[1:].strip() if negate else value
                if not value:
                    reject('Empty .dockerignore pattern.')
                value = posixpath.normpath(value).strip('/')
                if value != '.':
                    patterns.append((negate, docker_pattern(value)))
        with tarfile.open(fileobj=archive, mode='w', format=tarfile.PAX_FORMAT) as output:
            def visit(parent_fd, prefix):
                nonlocal total
                before = os.fstat(parent_fd)
                for name in sorted(os.listdir(parent_fd)):
                    relative = prefix + name
                    parts = tuple(relative.split('/'))
                    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        reject('Source contains a symlink or special file.')
                    if platform_path(parts) or (info.st_dev, info.st_ino) in protected_ids:
                        reject('Source contains platform configuration or credential storage.')
                    if mandatory_path(parts):
                        excluded.append(relative)
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(name, directory_flags, dir_fd=parent_fd)
                        try:
                            if unchanged(os.fstat(child)) != unchanged(info):
                                reject('Source changed during packaging.')
                            visit(child, relative + '/')
                        finally:
                            os.close(child)
                        if unchanged(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != unchanged(info):
                            reject('Source changed during packaging.')
                        continue
                    if info.st_nlink != 1:
                        reject('Hardlinked source files are not permitted.')
                    rejected = False
                    ancestors = ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
                    for negate, pattern in patterns:
                        if any(pattern.fullmatch(part) for part in ancestors):
                            rejected = not negate
                    if rejected and relative not in ('Dockerfile', '.dockerignore'):
                        excluded.append(relative)
                        continue
                    total += info.st_size
                    if total > LIMIT or len(included) >= 10000:
                        reject('Source exceeds 100 MiB or 10,000 files.')
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
                    with os.fdopen(fd, 'rb') as source:
                        opened = os.fstat(fd)
                        if unchanged(opened) != unchanged(info):
                            reject('Source changed during packaging.')
                        if relative == '.dockerignore' and unchanged(info) != unchanged(ignore_info):
                            reject('Source changed during packaging.')
                        entry = tarfile.TarInfo(relative)
                        entry.size, entry.mode = info.st_size, stat.S_IMODE(info.st_mode) & 0o777
                        output.addfile(entry, source)
                        if (unchanged(os.fstat(fd)) != unchanged(opened)
                                or unchanged(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != unchanged(opened)):
                            reject('Source changed during packaging.')
                    included.append(relative)
                if unchanged(os.fstat(parent_fd)) != unchanged(before):
                    reject('Source changed during packaging.')
            visit(root_fd, '')
        if unchanged(root.stat()) != unchanged(root_info):
            reject('Source changed during packaging.')
    finally:
        os.close(root_fd)
    if 'Dockerfile' not in included:
        reject('A root Dockerfile is required.')
    result = archive.getvalue()
    validate_archive(result)
    return {'included': sorted(included), 'excluded': sorted(excluded), 'total_bytes': total}, result
