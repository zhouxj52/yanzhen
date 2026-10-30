"""Human-authored source/contract fixture. No results or defect variants are embedded."""
from __future__ import annotations

import asyncio

from .projects import save_project

REQUIREMENT = '填写“验真协作”并保存，刷新页面后仍显示“验真协作”。'
HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>备注项目</title>
<style>body{font:18px sans-serif;max-width:620px;margin:80px auto;padding:24px;color:#172331}textarea{display:block;width:100%;padding:12px;font:inherit}button{margin:20px 0;padding:12px 28px;font:inherit}#saved{padding:20px;background:#edf3f8}</style>
<h1>项目备注</h1><label>备注<textarea id="note" placeholder="填写要保存的备注"></textarea></label><button id="save">保存</button><p id="message" role="status"></p><p id="saved"></p>
<script src="app.js"></script></html>'''
JS = '''document.querySelector('#saved').textContent = localStorage.getItem('note') || '';
document.querySelector('#save').onclick = function () {
  var value = document.querySelector('#note').value;
  if (value.length >= 1) {
    localStorage.setItem('note', value);
    document.querySelector('#saved').textContent = value;
    document.querySelector('#message').textContent = '保存成功';
  }
};'''


async def create_example(service):
    project = await asyncio.to_thread(save_project, {'index.html':HTML.encode(),'app.js':JS.encode(),'README.md':b'# Human-authored local acceptance fixture'},
                                      'example', {'source':'human_authored_counterexample_fixture; not an upstream benchmark'})
    preview = await asyncio.to_thread(service.previews.start, project['id'])
    contract = {'id':'note-persistence','title':'保存后刷新仍可读取备注',
        'probes':[{'id':'after-reload','source_type':'dom_text','phase':'after','locator':{'by':'css','value':'#saved'}}],
        'constraints':{'required_operations':[{'kind':'fill','value':'验真协作'},{'kind':'click'},{'kind':'reload'}]},
        'postconditions':[{'id':'persisted','left':'after-reload','expected':'验真协作','source':{'quote':REQUIREMENT}}]}
    actions=[{'id':'fill-note','kind':'fill','locator':{'by':'label','value':'备注'},'value':'验真协作'},
             {'id':'save-note','kind':'click','locator':{'by':'role','role':'button','value':'保存'}},
             {'id':'reload-note','kind':'reload'}]
    return {'project':project,'preview':preview,'requirements':REQUIREMENT,'supplied':{'contracts':[contract]},'actions':actions,
            'source':'human_authored_example; review and human freeze still required; no model calls'}
