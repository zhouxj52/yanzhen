"""Evidence rules compare observations, never infer success from a UI notification."""


def conflicts_for(result):
    evidence = result.evidence
    conflicts = []
    if result.kind == "save_persists":
        writes = [e for e in evidence if e.kind == "http" and e.data.get("method") == "PATCH" and e.data.get("status") == 200]
        reads = [e for e in evidence if e.kind == "http" and e.data.get("method") == "GET" and e.data.get("path") == "/records/2" and e.data.get("status") == 200]
        if writes and reads:
            expected = writes[-1].data.get("request_body",{}).get("note")
            actual = reads[-1].data.get("response",{}).get("note")
            if expected is not None and actual != expected:
                conflicts.append({"rule":"write_ack_vs_readback","title":"保存成功响应与重新查询不一致","evidence_ids":[writes[-1].id,reads[-1].id],"expected":expected,"actual":actual})
    if result.kind == "todo_persists":
        created = next((e for e in evidence if e.data.get("stage") == "after_add"),None)
        reload = next((e for e in evidence if e.data.get("stage") == "after_reload"),None)
        if created and reload and created.data["count"] == 1 and reload.data["count"] == 0:
            conflicts.append({"rule":"visible_vs_reload","title":"新增后的页面展示与刷新后不一致","evidence_ids":[created.id,reload.id],"expected":created.data["expected_title"],"actual_count":0})
    return conflicts
