"""验真开源应用功能验收包（单文件入口，随项目源码使用）。

用途：用未修改业务逻辑的 Spring Petclinic / OWASP Juice Shop，检查验真的
浏览器操作、输入边界、数据持久化、身份隔离、独立判断及证据导出能力。
包含 31 条人工根据上游规则转译的契约和操作计划。预期为 30 PASS + 1 FAIL；
最后一项是 Juice Shop 有意保留的越权读取缺陷，正确检出才算符合预期。
这些用例不是上游完整官方套件，也不代表自主需求生成或通用漏洞扫描成绩。

准备（在项目根目录运行，所有本机下载/缓存/临时文件放 D 盘）：
  1. 首次安装：powershell -File scripts/bootstrap.ps1
     已有环境可跳过；需要 Python 3.11–3.13、项目依赖和 Playwright Chromium。
  2. Petclinic：git clone https://github.com/spring-projects/spring-petclinic
     到 .cache/upstream/spring-petclinic，然后 git checkout 以下 PET_SHA。
     使用 D 盘 Java 17+ / Maven 构建；Maven 的 repo.local、user.home、
     MAVEN_USER_HOME、TEMP/TMP 均指向 D 盘目录。
     例如构建参数应包含 -Dmaven.repo.local=D:/openjiuwen/.cache/m2
     -Duser.home=D:/openjiuwen/.cache/java-home -Djava.io.tmpdir=D:/openjiuwen/.tmp
     并传 --batch-mode --no-transfer-progress -DskipTests -Dcheckstyle.skip
     -Dspring-javaformat.skip=true package。
     这里只构建目标，不宣称运行了上游 JUnit 全套测试。
  3. Juice Shop：下载下面 JUICE_ASSET_URL 对应官方 v20.3.0 / Node24 /
     Windows x64 包，校验 JUICE_ASSET_SHA256，解压到
     .cache/upstream/juice-shop_20.3.0，准备 D 盘 Node24。
     其他平台需从同一官方版本选择匹配平台的发布包/运行环境。
  4. 两个终端分别前台启动（不需要启动验真网页服务）：
     python scripts/benchmark_upstream.py --serve petclinic
     python scripts/benchmark_upstream.py --serve juice-shop
     默认监听 127.0.0.1:8781、8782，仅使用合成测试数据。

使用：
  以下 python 指项目虚拟环境的解释器；Windows 可用 .venv/Scripts/python.exe。
  python scripts/benchmark_upstream.py --list           # 无网络、无目标写入，列用例
  python scripts/benchmark_upstream.py --check          # 只读检查目标是否就绪
  python scripts/benchmark_upstream.py --approve-local-upstream-writes
  python scripts/benchmark_upstream.py --audit          # 离线核对最近一次原始证据
  python scripts/benchmark_upstream.py --only owner-create --approve-local-upstream-writes
  可选 --allow-model：额外执行两项 DeepSeek 下一步规划实验。需要本地 .env
  配置密钥，复用现有同一个累计 5 元预算账本；默认不调用大模型。

输出：.artifacts/upstream-benchmark-时间.json 与同名 .md，另有每条用例的
冻结标准、真实操作、截图和 ZIP。退出码 0=本轮全部符合预期，1=有不一致，
2=目标/配置尚未就绪。受阻和不确定均不算通过，子集不能冒充完整评测。
账户创建/登录及部分初态由准备阶段生成，不计入 Agent 自主步骤。
后端未逐例重置，因此本包不宣称已验证上游写入流程的最小化复现能力。
来源、历史参考口径和运行代码都在本文件；历史参考值不会被当成本次结果。
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('YZ_ARTIFACTS_DIR', str(ROOT / '.artifacts/verifyagent-service'))
os.environ.setdefault('TEMP', str(ROOT / '.tmp'))
os.environ.setdefault('TMP', str(ROOT / '.tmp'))

import httpx

from yanzhen.settings import initialize
from yanzhen.store import write_json
from yanzhen.verifyagent.schema import Action, Bundle, GenericContract, Run, RunInput, Target, digest, now
from yanzhen.verifyagent.repository import freeze, path, save_bundle, save_target
from yanzhen.verifyagent.engine import execute

PET_SHA = '500158f732419217507c7656904b8e6aa1bcc0d6'
PET = 'https://github.com/spring-projects/spring-petclinic/blob/' + PET_SHA
JUICE = 'https://github.com/juice-shop/juice-shop/blob/v20.3.0'
JUICE_ASSET_URL = 'https://github.com/juice-shop/juice-shop/releases/download/v20.3.0/juice-shop-20.3.0_node24_win32_x64.zip'
JUICE_ASSET_SHA256 = 'a25fc33b3b3565aae52381f63e6c9727790f67e8443ead02803a8eec7bdb7f57'
SOURCES = {
    'petclinic': {'repository': 'https://github.com/spring-projects/spring-petclinic', 'commit': PET_SHA, 'license': 'Apache-2.0'},
    'juice-shop': {'repository': 'https://github.com/juice-shop/juice-shop', 'release': 'v20.3.0', 'license': 'MIT',
        'asset_url': JUICE_ASSET_URL, 'asset_sha256': JUICE_ASSET_SHA256},
}
RESEARCHED_NOT_RUN = {
    'RealWorld': 'https://github.com/realworld-apps/realworld',
    'BrowserGym': 'https://github.com/ServiceNow/BrowserGym',
    'WebArena': 'https://github.com/web-arena-x/webarena',
    'MiniWoB++': 'https://github.com/Farama-Foundation/miniwob-plusplus',
}
REFERENCE_MEASUREMENT = {'date': '2026-10-26', 'protocol': 'upstream-business-acceptance-v2',
    'normal': '30/30 PASS', 'known_defect': '1/1 detected as FAIL', 'real_planning': '2/2 PASS, 6 provider requests',
    'scope': 'Historical selected-case measurement, not a promised score for another machine or a general autonomous success rate.',
    'calibration': 'An initial date-field contract incorrectly expected server .has-error although HTML min blocked submission. Its FAIL was retained; a new contract checks native invalid state and absent persisted data. These are different contract versions.'}
OWNER_TEST = PET + '/src/test/java/org/springframework/samples/petclinic/owner/OwnerControllerTests.java'
PET_TEST = PET + '/src/test/java/org/springframework/samples/petclinic/owner/PetControllerTests.java'
VISIT_TEST = PET + '/src/test/java/org/springframework/samples/petclinic/owner/VisitControllerTests.java'


def action(kind, **kwargs):
    return {'id': 'a-' + uuid.uuid4().hex[:10], 'kind': kind, **kwargs}


def nav(url):
    return action('navigate', url=url)


def fill(selector, value):
    return action('fill', locator={'by': 'css', 'value': selector}, value=value)


def click(label):
    return action('click', locator={'by': 'role', 'value': label})


def dom(selector, expected, *, visible=False, op='contains'):
    if selector == 'h2' and expected == 'Owner Information':
        selector = 'h2:text-is("Owner Information")'
    return ({'source_type': 'dom_visible' if visible else 'dom_text',
             'locator': {'by': 'css', 'value': selector}}, 'eq' if visible else op, expected)


def api_probe(url, expected, *, pointer=None, actor='anonymous', op='eq'):
    return ({'source_type': 'http_status' if pointer is None else 'http_json',
             'url': url, 'actor': actor, **({'pointer': pointer} if pointer is not None else {})}, op, expected)


def case(identifier, title, project, requirement, steps, checks, source, *, expected='pass', tags=(), prechecks=()):
    probes, posts, preconditions = [], [], []
    for phase, entries, predicates in [('before', prechecks, preconditions), ('after', checks, posts)]:
        for probe, op, value in entries:
            pid = f'p{len(probes)}'
            probes.append({'id': pid, 'phase': phase, **probe})
            predicates.append({'id': 'check-' + pid, 'left': pid, 'op': op, 'expected': value,
                               'source': {'quote': requirement}})
    # Freeze business steps, not redundant assertion tools. GET/POST and identity
    # obligations cannot be satisfied by a success message or an unrelated probe.
    obligations = []
    for step in steps:
        if step['kind'] in {'navigate', 'http_request', 'reload'}:
            obligations.append({k: step[k] for k in ('kind', 'actor', 'method', 'url', 'json_body') if k in step})
    contract = GenericContract(id=identifier, title=title, probes=probes, postconditions=posts,
        preconditions=preconditions, constraints={'max_steps': min(60, len(steps) + 8),
        'required_actions': sorted({a['kind'] for a in steps}), 'required_operations': obligations})
    return {'id': identifier, 'title': title, 'project': project, 'requirement': requirement,
            'actions': steps, 'contract': contract, 'expected': expected,
            'tags': list(tags), 'sources': source if isinstance(source, list) else [source]}


def pet_cases(marker):
    rows = []
    for identifier, query, expected in [('search-owner', 'Franklin', 'George Franklin'),
                                        ('search-trim', '  Franklin  ', 'George Franklin')]:
        rows.append(case(identifier, '按姓氏查找' if identifier == 'search-owner' else '查找自动去除首尾空白', 'petclinic',
            f'在 Find Owners 中查询姓氏 {query!r}，应显示 George Franklin 的 Owner Information。',
            [nav('/owners/find'), fill('#lastName', query), click('Find Owner')],
            [dom('body', expected), dom('h2', 'Owner Information')], OWNER_TEST, tags=['search']))
    rows.append(case('search-missing', '无匹配记录给出提示', 'petclinic',
        '查询不存在的姓氏时应提示 has not been found，并保留查找表单。',
        [nav('/owners/find'), fill('#lastName', marker + 'Missing'), click('Find Owner')],
        [dom('.help-inline', 'has not been found'), dom('#lastName', True, visible=True)], OWNER_TEST, tags=['negative-input']))

    def owner(identifier, values=None, invalid=None):
        fields = {'firstName': 'YZ' + marker, 'lastName': 'Benchmark', 'address': '12 Test Street',
                  'city': 'Hangzhou', 'telephone': '1316761638'}
        fields.update(values or {})
        steps = [nav('/owners/new')] + [fill('#' + k, v) for k, v in fields.items()] + [click('Add Owner')]
        if invalid:
            checks = [dom('.has-error #' + invalid, True, visible=True), dom('h2', 'Owner')]
            req = f'新建主人时 {invalid}={fields[invalid]!r} 不合法，应拒绝保存并标记该字段错误。'
        else:
            steps.append(action('reload'))
            checks = [dom('h2', 'Owner Information')] + [dom('body', fields[k]) for k in ('firstName', 'address', 'city', 'telephone')]
            req = '使用下列合法资料新建主人，保存并刷新后姓名、地址、城市、电话均应保持：' + json.dumps(fields, ensure_ascii=False)
        return case(identifier, '新建主人：' + identifier.removeprefix('owner-'), 'petclinic', req, steps, checks,
                    [OWNER_TEST, PET + '/src/main/java/org/springframework/samples/petclinic/owner/Owner.java'],
                    tags=['form', 'validation' if invalid else 'persistence'])
    rows += [owner('owner-create'), owner('owner-address-max', {'address': 'A' * 255}),
             owner('owner-city-max', {'city': 'C' * 80}),
             owner('owner-address-over', {'address': 'A' * 256}, 'address'),
             owner('owner-city-over', {'city': 'C' * 81}, 'city'),
             owner('owner-address-required', {'address': ''}, 'address'),
             owner('owner-name-required', {'firstName': ''}, 'firstName'),
             owner('owner-phone-short', {'telephone': '123456789'}, 'telephone'),
             owner('owner-phone-long', {'telephone': '12345678901'}, 'telephone'),
             owner('owner-phone-letters', {'telephone': 'abcdefghij'}, 'telephone')]
    rows.append(case('owner-edit', '编辑主人并刷新验证', 'petclinic',
        f'将测试主人 1 的城市改为 {marker}City，保存并刷新后应保留新城市。',
        [nav('/owners/1/edit'), fill('#city', marker + 'City'), click('Update Owner'), action('reload')],
        [dom('body', marker + 'City'), dom('h2', 'Owner Information')], OWNER_TEST, tags=['form', 'persistence']))

    for identifier, name, born, invalid in [('pet-create', 'Pet' + marker, '2020-02-12', None),
        ('pet-name-required', '', '2020-02-12', 'name'), ('pet-duplicate', 'Leo', '2020-02-12', 'name'),
        ('pet-future-birth', 'Future' + marker, '2099-01-01', 'birthDate')]:
        steps = [nav('/owners/1/pets/new'), fill('#name', name), fill('#birthDate', born),
                 action('select', locator={'by': 'css', 'value': '#type'}, value='cat'), click('Add Pet')]
        if invalid:
            checks = [dom('.has-error #' + invalid, True, visible=True)]
            req = f'主人 1 新建宠物 name={name!r}, birthDate={born!r}，应拒绝并标记 {invalid} 字段错误；原有宠物名 Leo 不可重复。'
        else:
            steps.append(action('reload'))
            checks, req = [dom('body', name)], f'主人 1 新增宠物 {name}，生日 {born}、类型 cat，保存刷新后应保留该宠物。'
        rows.append(case(identifier, '宠物：' + identifier.removeprefix('pet-'), 'petclinic', req, steps, checks, PET_TEST,
                         tags=['form', 'validation' if invalid else 'persistence']))
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for identifier, visit_date, description, invalid in [('visit-create', tomorrow, 'Visit' + marker, None),
        ('visit-required', tomorrow, '', 'description'), ('visit-description-over', tomorrow, 'D' * 256, 'description'),
        ('visit-date-today', date.today().isoformat(), 'Today' + marker, 'date')]:
        steps = [nav('/owners/1/pets/1/visits/new'), fill('#date', visit_date), fill('#description', description), click('Add Visit')]
        if invalid:
            checks = [dom('.has-error #' + invalid, True, visible=True)]
            req = f'新增就诊 date={visit_date!r}, description={description!r} 不合法，应标记 {invalid} 字段并拒绝保存；日期必须在未来，描述非空且最多 255 字符。'
        else:
            steps.append(action('reload'))
            checks, req = [dom('body', description)], f'主人 1 的宠物 1 新增 {visit_date} 就诊记录 {description}，保存刷新后应仍可查到。'
        if identifier == 'visit-date-today':
            # MVC tests exercise the server directly; the real template additionally
            # has input[min=tomorrow]. Its native invalid state prevents submission,
            # so expecting a server-generated .has-error here is a false oracle.
            invalid_probe, op, expected = dom('#date:invalid', True, visible=True)
            invalid_probe.update(phase='checkpoint', after_action='click')
            steps.append(nav('/owners/1'))
            checks = [(invalid_probe, op, expected), dom('body', description, op='not_contains')]
            req = f'就诊日期 {visit_date} 不在未来，浏览器应将日期输入标记为无效并阻止保存；打开主人详情不得出现本次描述 {description}。'
        rows.append(case(identifier, '就诊：' + identifier.removeprefix('visit-'), 'petclinic', req, steps, checks,
                         [VISIT_TEST, PET + '/src/main/resources/templates/fragments/inputField.html'],
                         tags=['form', 'validation' if invalid else 'persistence']))
    return rows


def prepare_juice(origin, marker):
    """Actual setup requests create disposable users. No tokens enter contracts/reports."""
    users = {}
    with httpx.Client(base_url=origin, timeout=30, trust_env=False) as client:
        client.get('/rest/products/search?q=apple').raise_for_status()

        def user(label, product=None):
            email, password = f'yz-{marker}-{label}@example.test', 'Benchmark-Only-942!'
            response = client.post('/api/Users', json={'email': email, 'password': password, 'passwordRepeat': password})
            response.raise_for_status()
            auth = client.post('/rest/user/login', json={'email': email, 'password': password})
            auth.raise_for_status()
            credentials = auth.json()['authentication']
            env = 'YZ_VERIFY_SECRET_UPSTREAM_' + label.upper()
            os.environ[env] = 'Bearer ' + credentials['token']
            users[label] = {'header_env': {'Authorization': env}}
            bid = int(credentials['bid'])
            item = None
            if product:
                result = client.post('/api/BasketItems', headers={'Authorization': os.environ[env]},
                    json={'ProductId': product, 'BasketId': bid, 'quantity': 1})
                result.raise_for_status()
                item = result.json()['data']['id']
            return bid, item

        alice, _ = user('alice')
        bob, _ = user('bob', 2)
        updater, update_item = user('updater', 1)
        deleter, delete_item = user('deleter', 1)
    return (alice, bob, updater, update_item, deleter, delete_item), users


def juice_cases(origin, marker, *, inventory_only=False):
    if inventory_only:
        # Placeholder IDs are used solely to render the offline case inventory.
        # This branch never executes a request or creates an acceptance result.
        alice, bob, updater, update_item, deleter, delete_item = 1, 2, 3, 1, 4, 2
        users = {name: {'header_env': {'Authorization': 'YZ_VERIFY_SECRET_UPSTREAM_' + name.upper()}}
                 for name in ('alice', 'bob', 'updater', 'deleter')}
    else:
        (alice, bob, updater, update_item, deleter, delete_item), users = prepare_juice(origin, marker)
    basket = lambda bid: f'/rest/basket/{bid}'
    request = lambda url, **kw: action('http_request', url=url, **kw)
    search_source = JUICE + '/routes/search.ts'
    basket_source = JUICE + '/routes/basket.ts'
    item_source = JUICE + '/routes/basketItems.ts'
    rows = [case('shop-search', '公开商品搜索', 'juice-shop', '搜索 apple 应成功并返回 Apple Juice (1000ml)。',
        [request('/rest/products/search?q=apple')], [api_probe('/rest/products/search?q=apple', 200),
        api_probe('/rest/products/search?q=apple', 'Apple Juice (1000ml)', pointer='/data/0/name')], search_source, tags=['search', 'api']),
        case('shop-search-empty', '无匹配商品返回空列表', 'juice-shop', '搜索不存在的商品应返回成功状态及空商品列表。',
        [request('/rest/products/search?q=' + marker)], [api_probe('/rest/products/search?q=' + marker, 200),
        api_probe('/rest/products/search?q=' + marker, [], pointer='/data')], search_source, tags=['search', 'negative-input']),
        case('shop-auth-required', '匿名访问购物车被拒绝', 'juice-shop', '未登录时不可读取测试用户购物车，应返回 401 或 403。',
        [request(basket(alice))], [api_probe(basket(alice), [401, 403], op='in')], JUICE + '/server.ts', tags=['authorization']),
        case('shop-own-empty', '本人购物车初始为空', 'juice-shop', '新测试账户 alice 应能读取本人空购物车。',
        [request(basket(alice), actor='alice')], [api_probe(basket(alice), 200, actor='alice'),
        api_probe(basket(alice), [], pointer='/data/Products', actor='alice')], basket_source, tags=['authorization', 'api']),
        case('shop-cart-add', '加入本人购物车后可重新查询', 'juice-shop', 'alice 将商品 1 数量 2 加入本人购物车，随后独立查询应得到该商品及数量 2。',
        [request('/api/BasketItems', actor='alice', method='POST', json_body={'ProductId': 1, 'BasketId': alice, 'quantity': 2})],
        [api_probe(basket(alice), 1, pointer='/data/Products/0/id', actor='alice'),
         api_probe(basket(alice), 2, pointer='/data/Products/0/BasketItem/quantity', actor='alice')], item_source, tags=['api', 'persistence']),
        case('shop-cart-update', '购物车数量修改', 'juice-shop', 'updater 将本人已有购物车条目数量改为 3，独立重新查询后应为 3。',
        [request(f'/api/BasketItems/{update_item}', actor='updater', method='PUT', json_body={'quantity': 3})],
        [api_probe(basket(updater), 3, pointer='/data/Products/0/BasketItem/quantity', actor='updater')], item_source, tags=['api', 'persistence']),
        case('shop-cart-delete', '移除购物车条目', 'juice-shop', 'deleter 移除本人购物车中唯一条目后，独立查询的商品列表应为空。',
        [request(f'/api/BasketItems/{delete_item}', actor='deleter', method='DELETE')],
        [api_probe(basket(deleter), [], pointer='/data/Products', actor='deleter')], JUICE + '/server.ts', tags=['api', 'persistence']),
        case('shop-write-other-denied', '常规跨账户加购不改变他人数据', 'juice-shop', 'alice 用普通单值 JSON 向 bob 购物车添加商品时，bob 的完整商品列表必须保持不变。',
        [request('/api/BasketItems', actor='alice', method='POST', json_body={'ProductId': 1, 'BasketId': bob, 'quantity': 1})],
        [api_probe(basket(bob), 2, pointer='/data/Products/0/id', actor='bob'),
         api_probe(basket(bob), 1, pointer='/data/Products/0/BasketItem/quantity', actor='bob')], item_source, tags=['authorization'],
        prechecks=[api_probe(basket(bob), 2, pointer='/data/Products/0/id', actor='bob')]),
        case('shop-read-other-known-bug', '已知缺陷：跨账户读取购物车', 'juice-shop',
        'bob 已有仅包含商品 2 的购物车；alice 不得读取 bob 的购物车，读取请求应返回 401 或 403。',
        [request(basket(bob), actor='alice')], [api_probe(basket(bob), [401, 403], actor='alice', op='in')],
        [basket_source, JUICE + '/data/static/challenges.yml'], expected='fail', tags=['authorization', 'known-upstream-defect'],
        prechecks=[api_probe(basket(bob), 2, pointer='/data/Products/0/id', actor='bob')])]
    cross_write = next(r for r in rows if r['id'] == 'shop-write-other-denied')
    # Compare the complete collection, not just its first item: an extra illicit
    # item must not pass because the existing item still happens to be present.
    from yanzhen.verifyagent.schema import Probe, Predicate
    cross_write['contract'].probes.extend([
        Probe(id='cart-before', source_type='http_json', phase='before', url=basket(bob), actor='bob', pointer='/data/Products'),
        Probe(id='cart-after', source_type='http_json', phase='after', url=basket(bob), actor='bob', pointer='/data/Products')])
    cross_write['contract'].postconditions.append(Predicate(id='full-cart-unchanged', left='cart-after', op='eq', right_probe='cart-before',
        source={'quote': cross_write['requirement']}))
    return rows, users


async def run_case(row, target, planner='manual', bundle=None):
    if bundle is None:
        bundle = Bundle(requirements=row['requirement'], target_id=target.id, provider='manual', contracts=[row['contract']])
        save_bundle(bundle)
        bundle = freeze(bundle.id, bundle.calculate_digest(), 'upstream-source-derived-benchmark-protocol-v1')
    request = RunInput(bundle_id=bundle.id, planner=planner,
        manual_actions=row['actions'] if planner == 'manual' else [], max_model_calls=6, max_seconds=180)
    run = Run(bundle_id=bundle.id, target_id=target.id, contract_digest=bundle.digest, planner=planner)
    write_json(path('runs', run.id) / 'contract.json', bundle.model_dump(mode='json'))

    async def approve(current, step):
        current.approvals.append({'action_id': step.id, 'action_digest': digest(step), 'approved': True,
            'timestamp': now(), 'reviewer': 'explicit-local-upstream-benchmark-cli',
            'scope': 'Disposable synthetic data on exact loopback benchmark origins only'})
        return True

    result = await execute(run, request, approve)
    actual = result.results[0]['verdict'] if result.results else 'blocked'
    output = {k: row[k] for k in ('id', 'title', 'project', 'requirement', 'sources', 'expected', 'tags')}
    output.update(actual=actual, matched_expectation=actual == row['expected'], run_id=run.id,
        bundle_id=bundle.id, contract_digest=bundle.digest, planner=planner,
        planning_scope='fixed_human_DSL' if planner == 'manual' else 'real_model_next_action_on_human_frozen_contract',
        steps=len(result.trace), tool_failures=sum(not t['ok'] for t in result.trace),
        evidence_count=len(result.evidence), elapsed_ms=result.usage['wall_time_ms'],
        model_calls=len(result.usage.get('calls', [])), prompt_tokens=result.usage.get('prompt_tokens', 0),
        completion_tokens=result.usage.get('completion_tokens', 0), error=result.error,
        reason=result.results[0].get('reason') if result.results else None,
        view_url='/static/verifyagent.html?run=' + run.id,
        archive_url='/api/verify/runs/' + run.id + '/artifacts/evidence.zip')
    print(json.dumps({k: output[k] for k in ('id', 'planner', 'actual', 'expected', 'steps', 'error')}, ensure_ascii=False), flush=True)
    return output, bundle


def inventory():
    shop, _ = juice_cases('', 'INVENTORY', inventory_only=True)
    return pet_cases('INVENTORY') + shop


def check_targets(projects=None):
    ready, rows = True, []
    with httpx.Client(timeout=10, trust_env=False) as client:
        for name, url in [('petclinic', 'http://127.0.0.1:8781/owners/find'),
                          ('juice-shop', 'http://127.0.0.1:8782/rest/products/search?q=apple')]:
            if projects is not None and name not in projects:
                continue
            try:
                response = client.get(url)
                ok = response.status_code == 200
                rows.append({'target': name, 'url': url, 'ready': ok, 'http_status': response.status_code})
            except httpx.HTTPError as exc:
                ok = False
                rows.append({'target': name, 'url': url, 'ready': False, 'error': type(exc).__name__})
            ready = ready and ok
    return ready, rows


def serve_target(name):
    """Foreground-only launcher. Target setup/runtime stays outside shipped source."""
    cache = ROOT / '.cache/upstream'
    env = {key: value for key, value in os.environ.items()
           if key not in {'YZ_DEEPSEEK_API_KEY', 'YZ_LLM_API_KEY', 'DEEPSEEK_API_KEY'}
           and not key.startswith('YZ_VERIFY_SECRET_')}
    env['TEMP'] = env['TMP'] = str(ROOT / '.tmp')
    if name == 'petclinic':
        work = cache / 'spring-petclinic'
        jar = work / 'target/spring-petclinic-4.0.0-SNAPSHOT.jar'
        java_home = os.getenv('JAVA_HOME') or ('D:/soft/Java/jdk-21' if Path('D:/soft/Java/jdk-21').exists() else '')
        java = str(Path(java_home) / 'bin' / ('java.exe' if os.name == 'nt' else 'java')) if java_home else shutil.which('java')
        if not java or not jar.is_file():
            raise ValueError('缺少 Java 或 Petclinic 构建结果；请按本文件 --help 中的准备步骤安装。')
        revision = subprocess.run(['git', '-C', str(work), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        if revision != PET_SHA:
            raise ValueError('Petclinic 版本不符合本评测的固定提交，请先检出 PET_SHA 并重新构建。')
        command = [java, '-Djava.io.tmpdir=' + env['TEMP'], '-Duser.home=' + str(ROOT / '.cache/java-home'),
            '-jar', str(jar), '--server.address=127.0.0.1', '--server.port=8781', '--spring.docker.compose.enabled=false']
    else:
        work = cache / 'juice-shop_20.3.0'
        package = work / 'package.json'
        node_cached = cache / 'node-v24.22.1-win-x64/node.exe'
        node = str(node_cached) if node_cached.is_file() else shutil.which('node')
        if not node or not package.is_file():
            raise ValueError('缺少 Node24 或 Juice Shop v20.3.0 官方发布包；请看 --help 和 JUICE_ASSET_URL。')
        if json.loads(package.read_text(encoding='utf-8'))['version'] != '20.3.0':
            raise ValueError('本协议要求 Juice Shop v20.3.0。')
        node_version = subprocess.run([node, '--version'], capture_output=True, text=True, check=True).stdout.strip()
        if not node_version.startswith('v24.'):
            raise ValueError('预编译目标要求 Node24，请使用匹配运行时。')
        preload = ROOT / '.tmp/upstream-loopback.cjs'
        preload.write_text("""// Launch boundary only; upstream business logic is unchanged.
const net = require('node:net');
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  const first = args[0];
  if (typeof first === 'number' || (typeof first === 'string' && /^\\d+$/.test(first))) {
    const cb = args.find(item => typeof item === 'function');
    return listen.call(this, {port: Number(first), host: '127.0.0.1'}, cb);
  }
  if (first && typeof first === 'object' && first.port !== undefined) args[0] = {...first, host: '127.0.0.1'};
  return listen.apply(this, args);
};
""", encoding='utf-8')
        env.update(PORT='8782', NODE_ENV='production')
        command = [node, '--require', str(preload), 'build/app.js']
    return subprocess.run(command, cwd=work, env=env).returncode


def audit_report(filename):
    from yanzhen.verifyagent.repository import load_run, load_bundle
    report = json.loads(filename.read_text(encoding='utf-8'))
    rows = report['cases'] + report['model_cases']
    files = evidence = 0
    for row in rows:
        run = load_run(row['run_id'])
        bundle = load_bundle(run.bundle_id)
        bundle.assert_frozen()
        assert run.contract_digest == bundle.digest == row['contract_digest']
        assert run.status == 'completed' and len(run.results) == 1
        assert run.results[0]['verdict'] == row['actual'] and len(run.trace) == row['steps']
        assert len(run.evidence) == row['evidence_count']
        assert row['matched_expectation'] == (row['actual'] == row['expected'])
        assert row['planner'] == run.planner and row['model_calls'] == len(run.usage.get('calls', []))
        if run.planner != 'manual':
            assert row['model_calls'] > 0 and row['prompt_tokens'] == run.usage['prompt_tokens'] > 0
            fixed = next(r for r in report['cases'] if r['id'] == row['id'])
            assert fixed['bundle_id'] == row['bundle_id'] and fixed['contract_digest'] == row['contract_digest']
        for item in run.evidence:
            assert item.content_hash == digest(item.model_dump(exclude={'content_hash'}))
            evidence += 1
        with zipfile.ZipFile(path('runs', run.id) / 'evidence.zip') as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['contract_digest'] == run.contract_digest
            for name, entry in manifest['files'].items():
                content = archive.read(name)
                assert len(content) == entry['size'] and hashlib.sha256(content).hexdigest() == entry['sha256']
                for variable in ('YZ_DEEPSEEK_API_KEY', 'YZ_LLM_API_KEY'):
                    secret = os.getenv(variable, '')
                    if secret:
                        assert secret.encode() not in content, 'Credential appeared in archive'
                files += 1
    assert report['summary']['manual_cases'] == len(report['cases'])
    assert report['summary']['manual_verdicts'] == dict(Counter(r['actual'] for r in report['cases']))
    print(json.dumps({'status': 'passed', 'runs': len(rows), 'archive_files_verified': files,
                      'sealed_evidence_verified': evidence, 'report': str(filename)}, ensure_ascii=False))


def write_markdown(report, destination):
    summary = report['summary']
    lines = ['# 验真开源应用功能验收结果', '', f"运行时间：{report['created_at']}；协议：{report['protocol']}。",
        '', '范围：人工冻结标准与固定步骤验证执行/判断内核，另列可选真实模型规划。子集结果、未运行项均不能当作完整通过。',
        '', f"- 正常要求：{summary['normal_pass']}/{summary['normal_total']} 通过。",
        f"- 已知缺陷：{summary['known_defects_detected']}/{summary['known_defects_total']} 正确检出。",
        f"- 真实规划：{summary['model_tasks_passed']}/{summary['model_tasks_total']} 通过；{summary['model_api_calls']} 次模型请求。",
        '', '| 项目 | 检查项 | 规划 | 预期 | 实际 | 符合预期 | 证据 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for row in report['cases'] + report['model_cases']:
        archive = path('runs', row['run_id']) / 'evidence.zip'
        relative = Path(os.path.relpath(archive, destination.parent)).as_posix()
        lines.append(f"| {row['project']} | [{row['title']}]({row['sources'][0]}) | {row['planner']} | {row['expected']} | {row['actual']} | {'是' if row['matched_expectation'] else '否'} | [ZIP]({relative}) |")
    lines += ['', '## 解释与限制', '', '已知越权样本应判 FAIL；它不是本项目新发现的零日漏洞。两项短模型任务不代表复杂项目的通用自主成功率。',
        '', '后端并未按用例自动重置，准备账户/登录不计入自主步骤；本轮不验证上游写入流程最小化复现。',
        '', '来源版本：']
    for project, source in SOURCES.items():
        lines.append(f"- [{project}]({source['repository']})：{source.get('commit') or source['release']}，{source['license']}。")
    lines += ['', '未运行：'] + ['- ' + item for item in report['not_run']]
    destination.write_text('\n'.join(lines) + '\n', encoding='utf-8')


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    read_modes = parser.add_mutually_exclusive_group()
    read_modes.add_argument('--list', action='store_true', help='Offline inventory; no target setup or execution')
    read_modes.add_argument('--check', action='store_true', help='Read-only readiness check')
    read_modes.add_argument('--serve', choices=['petclinic', 'juice-shop'], help='Run a prepared target in foreground')
    read_modes.add_argument('--audit', nargs='?', const='latest', help='Offline audit of a report, default latest local run')
    parser.add_argument('--approve-local-upstream-writes', action='store_true')
    parser.add_argument('--allow-model', action='store_true', help='Two bounded real planning tasks; shared existing 5 CNY ledger')
    parser.add_argument('--only', help='Comma-separated case ids for investigation; never merged into an earlier score')
    args = parser.parse_args()
    initialize()
    available = inventory()
    if args.list:
        print(json.dumps({'mode': 'inventory_only_NOT_EXECUTED', 'cases': [{k: r[k] for k in ('id', 'title', 'project', 'expected', 'sources')} for r in available],
            'sources': SOURCES, 'historical_reference_NOT_CURRENT_RESULTS': REFERENCE_MEASUREMENT,
            'researched_NOT_RUN': RESEARCHED_NOT_RUN}, ensure_ascii=False, indent=2))
        return 0
    if args.serve:
        return serve_target(args.serve)
    if args.audit:
        candidates = sorted((ROOT / '.artifacts').glob('upstream-benchmark-*.json'), key=lambda p: p.stat().st_mtime)
        if args.audit == 'latest' and not candidates:
            parser.error('尚无本地评测记录，请先运行一次。')
        audit_report(candidates[-1] if args.audit == 'latest' else Path(args.audit).resolve())
        return 0
    selected = {part.strip() for part in args.only.split(',') if part.strip()} if args.only is not None else None
    if selected == set():
        parser.error('--only 需要至少一个用例编号，使用 --list 查看。')
    if selected and selected - {r['id'] for r in available}:
        parser.error('未知用例编号：' + ', '.join(sorted(selected - {r['id'] for r in available})))
    projects = {row['project'] for row in available if selected is None or row['id'] in selected}
    ready, readiness = check_targets(projects)
    if args.check or not ready:
        print(json.dumps({'ready': ready, 'targets': readiness,
            'next': 'See --help; prepare and start the two pinned targets with --serve.'}, ensure_ascii=False, indent=2))
        return 0 if ready else 2
    if not args.approve_local_upstream_writes:
        parser.error('Pass --approve-local-upstream-writes to authorize disposable local benchmark setup/actions')
    os.environ['YZ_VERIFY_ALLOWED_ORIGINS'] = 'http://127.0.0.1:8781,http://127.0.0.1:8782'
    if args.allow_model:
        os.environ['YZ_ENABLE_MODEL'] = '1'
        os.environ['YZ_VERIFY_BUDGET_CNY'] = '5'
        os.environ['YZ_VERIFY_MAX_PAID_CALLS'] = '60'
    marker = 'YZ' + uuid.uuid4().hex[:10]
    shop, identities = juice_cases('http://127.0.0.1:8782', marker) if 'juice-shop' in projects else ([], {})
    cases = (pet_cases(marker) if 'petclinic' in projects else []) + shop
    targets = {name: Target(name='Upstream benchmark · ' + name, base_url=origin,
        interface='web' if name == 'petclinic' else 'api', environment='local', authorized=True,
        identities={} if name == 'petclinic' else identities,
        isolation_note='Dedicated upstream application process; synthetic unique users/entities. Browser sessions isolated, backend shared across cases; no namespace/reset API. Restart resets target DB; mutating minimization is not claimed.')
        for name, origin in [('petclinic', 'http://127.0.0.1:8781/'), ('juice-shop', 'http://127.0.0.1:8782/')] if name in projects}
    for target in targets.values():
        save_target(target)
    results, bundles = [], {}
    stamp = now().replace(':', '-').replace('+', '_')
    private = ROOT / '.artifacts' / ('upstream-benchmark-' + stamp + '.json')
    report = {'protocol': 'upstream-business-acceptance-v2', 'created_at': now(), 'subset': bool(selected),
        'scope': 'External app integration, source-derived human contracts; no autonomous specification score or WebArena score',
        'protocol_notes': ['Harness pilot corrected an ambiguous h2 locator, a boolean/contains type mismatch, and the exact upstream notFound message. Pilot runs are retained privately and are not pooled into this measurement.',
            'Upstream test expectations are manually translated into frozen contracts, not imported official full suites. No target business source was patched.',
            'Juice Shop loopback launch preload only changes bind address. Maven packaged Petclinic with upstream JUnit tests skipped; this report does not claim to have run those tests.'],
        'protocol_revisions': [{'case': 'visit-date-today', 'old_run_id': '4c39ccd9c2594b76ae3cad1815fe0781',
            'old_contract_digest': 'e3fd2470d7cea0ae5215b0a88c96f6af071c01805addfd363ccf718aa221daa8',
            'issue': 'v1 wrongly expected server-rendered .has-error after HTML input[min] already blocked form submission.',
            'correction': 'v2 captures native #date:invalid at click checkpoint, then verifies unique description is absent from owner detail. A new contract is frozen; the original FAIL is retained, never rewritten as PASS.',
            'source': PET + '/src/main/resources/templates/fragments/inputField.html'}],
        'sources': SOURCES,
        'isolation': 'Dedicated localhost processes and synthetic data; no per-case backend reset. API user creation/login/item setup are outside measured steps.',
        'cases': results, 'model_cases': [],
        'not_run': ['Full WebArena/BrowserGym official suite (Docker engine unavailable)', 'RealWorld shared E2E suite',
            'Autonomous natural-language contract generation on independently labeled corpus',
            'Mutation minimization on upstream apps (no reset/namespace facility)', 'Full OWASP challenge set',
            'Drag/drop, file upload, multi-tab or cross-origin workflows (not in current DSL)']}
    for row in cases:
        if selected and row['id'] not in selected:
            continue
        result, bundle = await run_case(row, targets[row['project']])
        results.append(result)
        bundles[row['id']] = bundle
        write_json(private, report)
    if args.allow_model:
        for identifier in ('search-owner', 'shop-search'):
            if identifier not in bundles:
                continue
            row = next(r for r in cases if r['id'] == identifier)
            result, _ = await run_case(row, targets[row['project']], 'deepseek', bundles[identifier])
            report['model_cases'].append(result)
            write_json(private, report)
    normal = [r for r in results if r['expected'] == 'pass']
    bugs = [r for r in results if r['expected'] == 'fail']
    report['summary'] = {'manual_cases': len(results), 'manual_verdicts': dict(Counter(r['actual'] for r in results)),
        'normal_pass': sum(r['actual'] == 'pass' for r in normal), 'normal_total': len(normal),
        'known_defects_detected': sum(r['actual'] == 'fail' for r in bugs), 'known_defects_total': len(bugs),
        'mismatches': [r['id'] for r in results if not r['matched_expectation']],
        'model_tasks_passed': sum(r['actual'] == 'pass' for r in report['model_cases']),
        'model_tasks_total': len(report['model_cases']),
        'model_api_calls': sum(r['model_calls'] for r in report['model_cases']),
        'model_mismatches': [r['id'] for r in report['model_cases'] if not r['matched_expectation']]}
    write_json(private, report)
    write_markdown(report, private.with_suffix('.md'))
    print(json.dumps({'summary': report['summary'], 'report': str(private), 'markdown': str(private.with_suffix('.md'))}, ensure_ascii=False, indent=2), flush=True)
    return 0 if not report['summary']['mismatches'] and not report['summary']['model_mismatches'] else 1


if __name__ == '__main__':
    try:
        exit_code = asyncio.run(main())
    except (FileNotFoundError, ValueError, httpx.HTTPError, subprocess.CalledProcessError) as exc:
        print(json.dumps({'status': 'not_ready', 'error_type': type(exc).__name__,
            'next': 'Run --help and --check; check local dependencies, pinned targets, and saved evidence.'}, ensure_ascii=False), file=sys.stderr)
        exit_code = 2
    raise SystemExit(exit_code)
