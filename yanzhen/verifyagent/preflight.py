"""Read-only project entry check used before contract generation. No LLM calls."""
from __future__ import annotations

import asyncio
import httpx

from .executor import ToolExecutor
from .schema import Run, Target
from .security import PolicyError, TargetPolicy


async def check_target(target: Target) -> dict:
    executor = None
    try:
        policy = TargetPolicy(target)
        run = Run(bundle_id='0'*32, target_id=target.id, contract_digest='connection-check', planner='read-only')
        executor = ToolExecutor(target, run, policy)
        actor = next(iter(target.identities), 'anonymous')
        async with asyncio.timeout(8):
            response = await executor.request(actor, 'GET', target.base_url)
        status = response['status']
        if 200 <= status < 400:
            return {'ready': True, 'state': 'ready', 'http_status': status, 'checked_url': response['url'], 'actor': actor,
                    'message': '已连接到项目，可以继续整理验收要求。此检查只读取入口，不代表功能验收通过。', 'model_calls': 0}
        if status in {401, 403}:
            return {'ready': False, 'state': 'needs_identity', 'http_status': status,
                    'message': '项目已响应，但需要登录或测试权限。请让项目开发者在高级设置中配置测试身份，再检查连接。', 'model_calls': 0}
        return {'ready': False, 'state': 'http_error', 'http_status': status,
                'message': f'项目入口返回 HTTP {status}。请确认地址能打开；API 项目请填写可读取的接口入口。', 'model_calls': 0}
    except PolicyError as exc:
        reason = str(exc)
        if 'ALLOW' in reason or 'allowlist' in reason:
            state, message = 'not_allowed', '这个地址尚未获得服务器授权。请让管理员把该项目的地址和端口加入允许列表，然后重启验真服务。'
        elif 'identity' in reason.lower() or 'secret' in reason.lower():
            state, message = 'needs_identity', '测试身份尚未配置完整。请检查高级设置中的身份引用与服务器本地配置。'
        elif 'control plane' in reason:
            state, message = 'control_plane', '这里填写的是待验收项目的地址，请不要填写验真工作台自己的地址。'
        else:
            state, message = 'unsupported_target', '当前只支持已授权的本机或内网 IP 测试地址，并要求页面和接口位于同一允许范围。公网域名和越界跳转暂不支持。'
        return {'ready': False, 'state': state, 'message': message, 'model_calls': 0}
    except (httpx.HTTPError, TimeoutError):
        return {'ready': False, 'state': 'unreachable', 'message': '暂时连接不上项目。请先启动项目，核对端口，并确认运行验真的这台电脑能打开它。', 'model_calls': 0}
    finally:
        if executor:
            await executor.close()
