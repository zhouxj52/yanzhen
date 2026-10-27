import asyncio
import io
import json
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from yanzhen import store
from yanzhen.verifyagent.projects import archive_files, directory_files, save_project, ProjectPreviews, folder, MANAGED_ORIGINS
from yanzhen.verifyagent.schema import Target
from yanzhen.verifyagent.security import PolicyError, TargetPolicy


def zip_bytes(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo('placeholder')
            info.filename = name  # Preserve malicious Windows separators on Windows too.
            archive.writestr(info, content)
    return data.getvalue()


@pytest.mark.parametrize('path', ['../escape.txt', 'C:/escape.txt', '/escape.txt', 'foo\\bar', 'foo/NUL.txt', 'foo./x'])
def test_zip_rejects_traversal_and_windows_ambiguity(path):
    with pytest.raises(ValueError):
        archive_files(zip_bytes({path: 'bad'}))


def test_zip_inspection_hashes_source_without_running_it(tmp_path, monkeypatch):
    files = archive_files(zip_bytes({'app/main.py': 'import os\nos.remove("never-executed")\n',
                                    'app/broken.py': 'def broken(:', 'app/.env': 'private-key',
                                    'app/node_modules/pkg/a.js': 'ignored', 'app/README.md': '# Example'}))
    report = save_project(files, 'zip', {'test': True})
    assert report['files'] == 3 and report['inspection']['python_files_parsed'] == 2
    assert report['inspection']['acceptance_verdict'] is None
    assert any(f['file'] == 'broken.py' and f['level'] == 'error' for f in report['inspection']['findings'])
    assert not (folder(report['id']) / 'source/.env').exists()
    assert report['state'] == 'needs_runtime'
    changed = save_project({**files, 'README.md': b'new version'}, 'zip', {})
    assert changed['source_sha256'] != report['source_sha256']


def test_directory_is_snapshot_and_obeys_roots(tmp_path, monkeypatch):
    source = tmp_path / 'input'
    source.mkdir()
    (source/'index.html').write_text('<h1>Original</h1>')
    (source/'.env').write_text('secret')
    monkeypatch.setenv('YZ_PROJECT_ALLOWED_ROOTS', str(source))
    report = save_project(directory_files(str(source)), 'directory', {})
    (source/'index.html').write_text('<h1>Changed</h1>')
    assert (folder(report['id'])/'source/index.html').read_text() == '<h1>Original</h1>'
    assert report['static_entry'] == 'index.html'
    with pytest.raises(ValueError, match='ROOTS'):
        directory_files(str(tmp_path))


def test_static_preview_is_real_and_stops(tmp_path, monkeypatch):
    report = save_project({'index.html': b'<h1>Snapshot preview</h1>'}, 'zip', {})
    previews = ProjectPreviews()
    try:
        entry = previews.start(report['id'])
        target = Target(name='source preview', base_url=entry['base_url'], authorized=True, environment='test', project_id=report['id'])
        policy = TargetPolicy(target, allowed='')
        response = httpx.get(policy.validate('.'), trust_env=False)
        assert response.status_code == 200 and 'Snapshot preview' in response.text
        assert "connect-src 'self'" in response.headers['content-security-policy']
        assert httpx.get(entry['base_url']+'.env', trust_env=False).status_code == 403
        previews.stop(report['id'])
        with pytest.raises(PolicyError, match='ALLOW'):
            TargetPolicy(target, allowed='')
    finally:
        previews.close()


def test_api_upload_requires_local_operator_and_never_claims_acceptance(tmp_path):
    from yanzhen.app import create_app
    with TestClient(create_app()) as client:
        content = zip_bytes({'index.html': '<h1>Uploaded project</h1>'})
        assert client.post('/api/verify/projects/upload', content=content).status_code == 422
        assert client.post('/api/verify/projects/upload', content=content, headers={'X-Project-Authorized':'1','Origin':'https://foreign.example'}).status_code == 403
        response = client.post('/api/verify/projects/upload', content=content, headers={'X-Project-Authorized':'1'})
        assert response.status_code == 200
        project = response.json()
        assert project['inspection']['model_calls'] == 0 and project['inspection']['acceptance_verdict'] is None
        preview = client.post(f'/api/verify/projects/{project["id"]}/preview', json={}).json()
        target = client.post('/api/verify/targets', json={'name':'uploaded','base_url':preview['base_url'],'environment':'test','authorized':True,'project_id':project['id']}).json()
        assert target['project_id'] == project['id']
        assert client.post('/api/verify/targets/check',json=target).json()['ready']


def test_public_hostname_is_allowlisted_and_pinned(monkeypatch):
    target = Target(name='public staging', base_url='https://stage.example.org/app/', environment='test', authorized=True)
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k: [(2,1,6,'',('93.184.216.34',443))])
    with pytest.raises(PolicyError, match='ALLOW'):
        TargetPolicy(target, allowed='')
    policy = TargetPolicy(target, allowed='https://stage.example.org')
    assert policy.validate('api/data') == 'https://stage.example.org:443/app/api/data'
    assert policy.pinned_ip == '93.184.216.34'
    with pytest.raises(PolicyError):
        policy.validate('https://other.example.org')
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k: [(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(PolicyError, match='rebinding'):
        TargetPolicy(target, allowed='https://stage.example.org')


def test_github_source_locks_commit_and_rejects_foreign_url(monkeypatch):
    from yanzhen.verifyagent.projects import github_files
    sha = 'a'*40
    requests = []
    def handle(request):
        requests.append(str(request.url))
        if request.url.host == 'codeload.github.com':
            assert sha in request.url.path
            return httpx.Response(200, content=zip_bytes({'repo-abc/index.html':'<h1>From GitHub</h1>'}))
        if '/commits/' in request.url.path:
            return httpx.Response(200, json={'sha':sha})
        return httpx.Response(200, json={'default_branch':'main'})
    original = httpx.AsyncClient
    monkeypatch.setattr('yanzhen.verifyagent.projects.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    files, provenance = asyncio.run(github_files('https://github.com/sample/site'))
    assert provenance['commit'] == sha and files['index.html'] == b'<h1>From GitHub</h1>'
    with pytest.raises(ValueError):
        asyncio.run(github_files('https://foreign.example/sample/site'))


def test_official_openjiuwen_runtime_calls_metered_provider_once(monkeypatch):
    pytest.importorskip('openjiuwen')
    from yanzhen.verifyagent.planning import ModelClient
    from yanzhen.verifyagent.schema import Decision
    monkeypatch.setenv('YZ_ENABLE_MODEL', '1')
    monkeypatch.setenv('YZ_OPENJIUWEN_MODEL_PROVIDER', 'deepseek')
    monkeypatch.setenv('YZ_DEEPSEEK_API_KEY', 'explicit-unit-mock')
    monkeypatch.setenv('YZ_VERIFY_BUDGET_CNY', '5')
    monkeypatch.setenv('YZ_VERIFY_PRICED_MODEL', 'deepseek-flash')
    monkeypatch.setenv('YZ_VERIFY_INPUT_CNY_PER_MILLION', '2')
    monkeypatch.setenv('YZ_VERIFY_OUTPUT_CNY_PER_MILLION', '8')
    paid = []
    def respond(request):
        paid.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'finished':True,'explanation':'Explicit mocked inference, actual SDK runtime'})},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':10}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            planner = ModelClient('openjiuwen', client=transport)
            assert (await planner.complete('exploration',{},Decision)).finished
            runtime = planner.calls[-1]['runtime']
            assert [e['node'] for e in runtime['nodes'] if e['state']=='completed'] == ['request','model_planning','schema_validation','return']
            assert runtime['sdk_version'] == '0.1.19.post2' and runtime['native_tools'] == []
            assert planner.usage()['prompt_tokens'] == 100
    asyncio.run(scenario())
    assert len(paid) == 1
    ledger = json.loads((store.ARTIFACTS/'verifyagent/model-budget.json').read_text())
    assert len(ledger['records']) == 1 and ledger['records'][0]['provider'] == 'deepseek'


def test_pinned_https_preserves_host_sni_and_domain_cookie(tmp_path):
    import ssl
    import threading
    from datetime import datetime, timedelta, timezone
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from yanzhen.verifyagent.network import PinnedTransport
    hostname = 'stage.example.org'
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    current = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(current-timedelta(days=1))
            .not_valid_after(current+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path/'cert.pem', tmp_path/'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Set-Cookie', f'fixture=session; Domain={hostname}; Path=/; Secure')
            self.end_headers()
            self.wfile.write(json.dumps({'host':self.headers['Host'],'cookie':self.headers.get('Cookie')}).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    context.set_servername_callback(lambda socket, name, ctx: seen.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    trust = ssl.create_default_context(cafile=str(cert_path))
    async def scenario():
        url = f'https://{hostname}:{server.server_port}/'
        async with httpx.AsyncClient(transport=PinnedTransport(hostname, '127.0.0.1', ssl_context=trust), trust_env=False) as client:
            assert (await client.get(url)).json()['host'] == f'{hostname}:{server.server_port}'
            assert (await client.get(url)).json()['cookie'] == 'fixture=session'
        async with httpx.AsyncClient(transport=PinnedTransport('wrong.example.org', '127.0.0.1', ssl_context=trust), trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(f'https://wrong.example.org:{server.server_port}/')
    try:
        asyncio.run(scenario())
        assert hostname in seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
