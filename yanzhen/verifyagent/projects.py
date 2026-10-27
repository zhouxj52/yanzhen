"""Bounded source intake. Source inspection never counts as functional acceptance."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import uuid
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlsplit

import httpx

from .. import store
from ..settings import ROOT
from ..store import safe_id, write_json

MAX_ARCHIVE = 20 * 1024 * 1024
MAX_TOTAL = 80 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_FILES = 5000
SKIP = {'.git', '.hg', '.svn', '.venv', 'venv', 'node_modules', '__pycache__', '.cache', '.tmp', '.artifacts', '.ssh', '.aws', '.azure', '.idea'}
MANAGED_ORIGINS: set[str] = set()


def folder(identifier):
    return store.ARTIFACTS / 'verifyagent' / 'projects' / safe_id(identifier)


def load_project(identifier):
    return json.loads((folder(identifier) / 'project.json').read_text(encoding='utf-8'))


def relative_name(name):
    # Apply Windows rules even when the server is running on Linux.
    if not name or name in {'.', '..'} or '\\' in name or re.search(r'[\x00-\x1f:]', name):
        raise ValueError('压缩包包含无效路径')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {'..', ''} or p.endswith((' ', '.')) for p in path.parts):
        raise ValueError('压缩包路径越界或存在歧义')
    if any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p, re.I) for p in path.parts):
        raise ValueError('压缩包包含保留设备名')
    return path.as_posix()


def excluded(name):
    parts = PurePosixPath(name).parts
    leaf = parts[-1].lower()
    return any(p.lower() in SKIP for p in parts) or leaf.startswith('.env') and leaf not in {'.env.example', '.env.sample'} or leaf.endswith(('.pem', '.key', '.p12', '.pfx', '.zip', '.log', '.pyc')) or leaf in {'id_rsa', 'id_ed25519', 'credentials', '.npmrc', '.pypirc'}


def archive_files(data):
    if len(data) > MAX_ARCHIVE:
        raise ValueError('ZIP 不得超过 20 MB')
    output, seen, total = {}, set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > MAX_FILES:
                raise ValueError('ZIP 条目不得超过 5000 个')
            for item in archive.infolist():
                name = relative_name(item.orig_filename.rstrip('/'))
                if name.casefold() in seen:
                    raise ValueError('ZIP 包含重复或大小写冲突的路径')
                seen.add(name.casefold())
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ValueError('ZIP 不接受链接或特殊文件')
                if item.is_dir() or excluded(name):
                    continue
                total += item.file_size
                if item.file_size > MAX_FILE or total > MAX_TOTAL:
                    raise ValueError('源码文件过大：单文件限 16 MB，解压总量限 80 MB')
                if item.flag_bits & 1:
                    raise ValueError('不支持加密 ZIP')
                output[name] = archive.read(item)
    except zipfile.BadZipFile:
        raise ValueError('文件不是有效的 ZIP 压缩包') from None
    names = {n.casefold() for n in output}
    if any(parent.as_posix().casefold() in names for name in output for parent in PurePosixPath(name).parents if parent.as_posix() != '.'):
        raise ValueError('ZIP 中的文件与目录路径冲突')
    # A conventional repository wrapper is not part of the project root.
    roots = {n.split('/')[0] for n in output}
    if len(roots) == 1 and all('/' in n for n in output):
        output = {n.split('/', 1)[1]: content for n, content in output.items()}
    return output


def directory_files(location):
    raw = Path(location).expanduser()
    allowed = [Path(p).resolve() for p in os.getenv('YZ_PROJECT_ALLOWED_ROOTS', str(ROOT)).split(';') if p.strip()]
    if not raw.is_absolute() or not raw.is_dir():
        raise ValueError('请填写验真服务器上的绝对目录路径')
    source = raw.resolve()
    if not any(source == root or root in source.parents for root in allowed):
        raise ValueError('目录不在 YZ_PROJECT_ALLOWED_ROOTS 中；多目录用分号分隔')
    output, total, count = {}, 0, 0
    for current, dirs, files in os.walk(source, followlinks=False):
        def regular(path):
            return not path.is_symlink() and not (getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
        dirs[:] = [d for d in dirs if not excluded((Path(current)/d).relative_to(source).as_posix()) and regular(Path(current)/d)]
        for leaf in files:
            count += 1
            if count > MAX_FILES:
                raise ValueError('目录文件数超过 5000，请先移除构建产物或使用精简 ZIP')
            path = Path(current) / leaf
            name = relative_name(path.relative_to(source).as_posix())
            if excluded(name) or not regular(path) or not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            if size > MAX_FILE or total > MAX_TOTAL:
                raise ValueError('目录超过单文件 16 MB / 总量 80 MB 的限制')
            output[name] = path.read_bytes()
    return output


async def github_files(url, ref=''):
    parsed = urlsplit(url)
    match = re.fullmatch(r'/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not match or parsed.query or parsed.fragment:
        raise ValueError('请填写公开仓库根链接：https://github.com/组织/仓库；分支或提交单独填写')
    owner, name = match.groups()
    base = f'https://api.github.com/repos/{owner}/{name}'
    async with httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client:
        if not ref:
            response = await client.get(base)
            if response.status_code != 200:
                raise ValueError(f'GitHub 仓库读取失败（HTTP {response.status_code}）；目前支持公开仓库')
            ref = response.json()['default_branch']
        response = await client.get(base + '/commits/' + quote(ref, safe=''))
        if response.status_code != 200:
            raise ValueError(f'GitHub 提交读取失败（HTTP {response.status_code}）')
        sha = response.json()['sha']
        if not re.fullmatch('[a-f0-9]{40}', sha):
            raise ValueError('GitHub 返回无效提交标识')
        payload = bytearray()
        async with client.stream('GET', f'https://codeload.github.com/{owner}/{name}/zip/{sha}') as response:
            if response.status_code != 200:
                raise ValueError(f'源码下载失败（HTTP {response.status_code}）')
            async for chunk in response.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > MAX_ARCHIVE:
                    raise ValueError('仓库压缩包超过 20 MB，请上传精简 ZIP')
    return archive_files(payload), {'repository': f'https://github.com/{owner}/{name}', 'requested_ref': ref, 'commit': sha}


def save_project(files, kind, provenance):
    if not files:
        raise ValueError('没有可检查的源码文件（依赖、缓存和凭据文件会被排除）')
    identifier = uuid.uuid4().hex
    destination = folder(identifier)
    manifest = {n: {'size': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for n, v in sorted(files.items())}
    tree_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    findings, stacks, commands = [], [], []
    def text(name):
        return files.get(name, b'').decode('utf-8-sig', errors='replace')
    def finding(level, file, message):
        findings.append({'level': level, 'file': file, 'message': message})
    if 'package.json' in files:
        stacks.append('Node.js / 前端')
        try:
            package = json.loads(text('package.json'))
            scripts = package.get('scripts', {})
            for key in ('dev', 'start', 'build', 'test'):
                if key in scripts:
                    commands.append({'label': key, 'command': f'npm run {key}', 'declared_script': str(scripts[key])[:600], 'executed': False})
            if not any(key in scripts for key in ('test', 'test:e2e')):
                finding('attention', 'package.json', '没有声明 test / test:e2e 脚本，需要补充自动化测试入口。')
        except (ValueError, AttributeError):
            finding('error', 'package.json', 'package.json 不是有效的项目配置。')
    if 'pyproject.toml' in files or 'requirements.txt' in files:
        stacks.append('Python')
    if 'pom.xml' in files or 'build.gradle' in files:
        stacks.append('Java')
    if 'go.mod' in files:
        stacks.append('Go')
    if not any(PurePosixPath(n).name.lower().startswith('readme') for n in files):
        finding('attention', '', '缺少 README，其他人难以复现运行环境。')
    if not any(PurePosixPath(n).name.lower().startswith(('test_', 'test.', 'spec.')) or '/tests/' in '/'+n or '.test.' in n or '.spec.' in n for n in files):
        finding('attention', '', '未发现常见测试文件；这不等同于功能存在缺陷。')
    python_count = 0
    import ast
    for name, content in files.items():
        if name.endswith('.py'):
            python_count += 1
            try:
                ast.parse(content, filename=name)
            except (SyntaxError, ValueError) as exc:
                finding('error', name, f'Python 静态语法检查失败：第 {getattr(exc, "lineno", "? ")} 行')
    # Serve only already-built static sites. Source frameworks require a real build/backend.
    entry = next((n for n in ('index.html', 'dist/index.html', 'build/index.html', 'public/index.html') if n in files), None)
    static_ready = bool(entry) and 'package.json' not in files and not stacks
    if static_ready:
        stacks.append('静态 HTML')
    for name, content in files.items():
        path = destination / 'source' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    result = {'id': identifier, 'kind': kind, 'provenance': provenance, 'source_sha256': tree_hash,
              'files': len(files), 'bytes': sum(len(v) for v in files.values()), 'stacks': stacks or ['待确认技术栈'],
              'inspection': {'python_files_parsed': python_count, 'findings': findings, 'model_calls': 0, 'acceptance_verdict': None},
              'commands': commands, 'static_entry': entry if static_ready else None,
              'state': 'static_preview_available' if static_ready else 'needs_runtime',
              'next_step': '可启动只读静态预览，随后按需求实际验收。' if static_ready else '已建立源码快照并检查项目结构。按项目 README 启动服务，再关联运行地址，继续功能验收。',
              'scope': '源码接入与静态预检；未执行依赖安装、项目脚本或功能验收。', 'created_at': datetime.now(timezone.utc).isoformat()}
    write_json(destination / 'manifest.json', manifest)
    write_json(destination / 'project.json', result)
    return result


class ProjectPreviews:
    def __init__(self):
        self.servers = {}

    def start(self, identifier):
        project = load_project(identifier)
        if not project['static_entry']:
            raise ValueError('该项目需要构建或后端，请按 README 启动后关联真实运行地址')
        if identifier in self.servers:
            return self.servers[identifier][1]
        root = (folder(identifier) / 'source' / project['static_entry']).parent.resolve()
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root), **kwargs)
            def log_message(self, *args):
                pass
            def list_directory(self, path):
                self.send_error(403)
                return None
            def send_head(self):
                name = unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
                try:
                    candidate = (root / relative_name(name)).resolve()
                    if root not in candidate.parents or excluded(name):
                        raise ValueError()
                except ValueError:
                    self.send_error(403)
                    return None
                return super().send_head()
            def end_headers(self):
                self.send_header('Content-Security-Policy', "default-src 'self' data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'")
                self.send_header('X-Content-Type-Options', 'nosniff')
                super().end_headers()
        if len(self.servers) >= 8:
            raise ValueError('同时最多预览 8 个项目，请先停止其他预览')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        base = f'http://127.0.0.1:{server.server_port}'
        MANAGED_ORIGINS.add(base)
        result = {'project_id': identifier, 'base_url': base+'/', 'state': 'running', 'scope': '只读静态文件服务；未执行项目启动脚本'}
        self.servers[identifier] = (server, result)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return result

    def stop(self, identifier):
        row = self.servers.pop(identifier, None)
        if row:
            MANAGED_ORIGINS.discard(row[1]['base_url'].rstrip('/'))
            row[0].shutdown()
            row[0].server_close()

    def close(self):
        for identifier in list(self.servers):
            self.stop(identifier)
