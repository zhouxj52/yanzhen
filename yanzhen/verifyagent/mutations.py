"""AST-bounded static JavaScript mutations; never execute source during discovery."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import PurePosixPath

from .projects import folder, load_project, relative_name
from .schema import digest

LABELS = {'drop_storage_write': '移除浏览器存储写入', 'shift_boundary': '改变边界包含关系', 'invert_equality': '反转相等条件'}


def source_files(identifier):
    project = load_project(identifier)
    manifest = json.loads((folder(identifier) / 'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest() != project['source_sha256']:
        raise ValueError('源码清单已变化，请重新导入并验收正常版本')
    output = {}
    for name, entry in manifest.items():
        path = folder(identifier) / 'source' / relative_name(name)
        if path.is_symlink() or not path.is_file():
            raise ValueError('源码快照文件缺失或被替换')
        content = path.read_bytes()
        if len(content) != entry['size'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('源码快照内容已变化，请重新导入')
        output[name] = content
    return output


def scripts(name, text):
    if name.endswith(('.js', '.mjs')):
        return [(0, text, 'module')]
    if not name.endswith(('.html', '.htm')):
        return []
    found = []
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    class Parser(HTMLParser):
        enabled = False
        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            self.enabled = tag == 'script' and 'src' not in attributes and attributes.get('type', '').lower() in {'', 'module', 'text/javascript', 'application/javascript'}
        def handle_endtag(self, tag):
            if tag == 'script': self.enabled = False
        def handle_data(self, data):
            if self.enabled:
                line, column = self.getpos()
                found.append((offsets[line-1]+column, data, 'module'))
    Parser(convert_charrefs=False).feed(text)
    return found


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def member(node):
    if node.get('type') == 'Identifier': return node['name']
    if node.get('type') == 'MemberExpression':
        prop = node['property']
        key = prop.get('value') if node.get('computed') else prop.get('name')
        if isinstance(key, str): return member(node['object']) + '.' + key
    return ''


def discover(files, limit=40):
    import esprima
    candidates, skipped = [], []
    for name, content in sorted(files.items()):
        if not name.endswith(('.js', '.mjs', '.html', '.htm')):
            continue
        if len(content) > 524288:
            skipped.append({'file':name, 'reason':'超过 512 KiB 的脚本文件暂不变异'})
            continue
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            skipped.append({'file':name, 'reason':'非 UTF-8 文本'})
            continue
        # Keep offsets relative to the exact decoded text, including any BOM.
        text = content.decode('utf-8')
        for offset, code, mode in scripts(name, text):
            try:
                tree = esprima.parseModule(code, {'range':True, 'tokens':True}).toDict()
            except (esprima.Error, RecursionError):
                skipped.append({'file':name, 'reason':'超出 ECMAScript 2017 语法支持或语法无效；未执行此脚本'})
                continue
            for node in walk(tree.get('body', [])):
                changes = []
                if node.get('type') == 'CallExpression' and member(node.get('callee', {})) in {'localStorage.setItem','sessionStorage.setItem','window.localStorage.setItem','window.sessionStorage.setItem'}:
                    changes.append(('drop_storage_write', *node['range'], '(void 0)'))
                if node.get('type') == 'BinaryExpression' and node.get('operator') in {'>=','>','<=','<','===','!==','==','!='}:
                    op = node['operator']
                    matching = [t for t in tree['tokens'] if t['type']=='Punctuator' and t['value']==op and node['left']['range'][1] <= t['range'][0] < node['right']['range'][0]]
                    if len(matching) == 1:
                        token = matching[0]
                        replacement = {'>=':'>','>':'>=','<=':'<','<':'<=','===':'!==','!==':'===','==':'!=','!=':'=='}[op]
                        changes.append(('shift_boundary' if op in {'>=','>','<=','<'} else 'invert_equality', *token['range'], replacement))
                for operator, start, end, replacement in changes:
                    if len(candidates) >= limit:
                        return candidates, skipped
                    start, end = start+offset, end+offset
                    candidate = {'file':name, 'operator':operator, 'label':LABELS[operator], 'start':start, 'end':end,
                                 'before':text[start:end], 'after':replacement, 'file_sha256':hashlib.sha256(content).hexdigest(),
                                 'line':text[:start].count('\n')+1}
                    candidate['id'] = digest(candidate)[:24]
                    candidates.append(candidate)
    return candidates, skipped


def apply(files, candidate):
    import esprima
    original = files[candidate['file']]
    if hashlib.sha256(original).hexdigest() != candidate['file_sha256']:
        raise ValueError('变异候选与原文件哈希不一致')
    text = original.decode('utf-8')
    start, end = candidate['start'], candidate['end']
    if text[start:end] != candidate['before'] or candidate['operator'] not in LABELS:
        raise ValueError('变异补丁已失效')
    modified = text[:start] + candidate['after'] + text[end:]
    for offset, code, mode in scripts(candidate['file'], modified):
        esprima.parseModule(code)  # Syntax validation, never eval or import the target.
    return {**files, candidate['file']:modified.encode('utf-8')}
