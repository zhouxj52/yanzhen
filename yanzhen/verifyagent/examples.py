"""Human-authored sample contracts, not inference or executable business adapters."""
from yanzhen.verifyagent.schema import Action, GenericContract, Target, Identity

AUTH_REQUIREMENT = "普通用户可查看自己的订单，但不能访问其他用户的订单。"
SAVE_REQUIREMENT = "用户保存的数据在刷新后必须保持一致。"


def target(origin, variant="healthy", interface="web"):
    return Target(name="Disposable orders and notes " + variant,base_url=origin + "/app/" + variant + "/",environment="local",authorized=True,interface=interface,api_description_urls=['api/schema'],
                  identities={"alice":Identity(header_env={"X-Test-Actor":"YZ_VERIFY_SECRET_ALICE"}),"bob":Identity(header_env={"X-Test-Actor":"YZ_VERIFY_SECRET_BOB"})},
                  namespace_header="X-Verify-Sandbox",isolation_note="Fixture v1.0 creates independent backend state for each executor-issued namespace")


def authorization():
    c = GenericContract.model_validate({"id":"order-access","title":"订单归属边界", "probes":[
        {"id":"owner_setup","source_type":"http_json","phase":"before","actor":"bob","url":"api/orders/2","pointer":"/owner"},
        {"id":"own","source_type":"http_status","actor":"alice","url":"api/orders/1"},
        {"id":"foreign","source_type":"http_status","actor":"alice","url":"api/orders/2"}],
        "preconditions":[{"id":"other_order_exists","left":"owner_setup","expected":"bob","source":{"quote":"其他用户的订单","basis":"assumption","explanation":"Verify ownership through the second identity before testing the access boundary"}}],
        "postconditions":[{"id":"own_allowed","left":"own","expected":200,"source":{"quote":"普通用户可查看自己的订单"}},
                          {"id":"foreign_denied","left":"foreign","expected":403,"source":{"quote":"不能访问其他用户的订单","basis":"assumption","explanation":"The reviewed test environment uses HTTP 403 for denial"}}]})
    actions=[Action(id="read-own",kind="http_request",actor="alice",url="api/orders/1"),Action(id="read-other",kind="http_request",actor="alice",url="api/orders/2",depends_on=["read-own"])]
    return c, actions


def persistence(*, api_only=False, drift=False):
    if api_only:
        probes=[{"id":"ack","source_type":"http_json","phase":"checkpoint","after_action":"http_request","url":"api/note","pointer":"/note"},
                {"id":"readback","source_type":"http_json","url":"api/note","pointer":"/note"}]
        # The expected input is reviewed test data. The oracle reads it independently.
        post=[{"id":"saved_value","left":"readback","expected":"验真独立验收","source":{"quote":SAVE_REQUIREMENT,"basis":"assumption","explanation":"Use approved synthetic text as test input"}}]
        actions=[Action(id="save",kind="http_request",url="api/note",method="PATCH",json_body={"note":"验真独立验收"}),Action(id="read",kind="http_request",url="api/note",depends_on=["save"])]
        required=["http_request"]
    else:
        probes=[{"id":"ui_ack","source_type":"dom_text","phase":"checkpoint","after_action":"click","locator":{"by":"testid","value":"saved"}},
                {"id":"readback","source_type":"http_json","url":"api/note","pointer":"/note"},
                {"id":"refreshed_dom","source_type":"dom_text","locator":{"by":"testid","value":"readback"}}]
        post=[{"id":"ui_vs_api","left":"readback","right_probe":"ui_ack","source":{"quote":SAVE_REQUIREMENT}},
              {"id":"ui_vs_refresh","left":"refreshed_dom","right_probe":"ui_ack","source":{"quote":SAVE_REQUIREMENT}}]
        actions=[Action(id="type-note",kind="fill",locator={"by":"label","value":"备注"},value="验真独立验收"),
                 Action(id="save",kind="click",locator={"by":"role","role":"button","value":"应用更改" if drift else "保存"},depends_on=["type-note"]),
                 Action(id="reload",kind="reload",depends_on=["save"])]
        required=["fill","click","reload"]
    c=GenericContract.model_validate({"id":"durable-note","title":"保存与刷新一致性","probes":probes,"constraints":{"required_actions":required,"required_operations":[{"kind":"http_request","method":"PATCH","url":"api/note","json_body":{"note":"验真独立验收"}}] if api_only else []},"postconditions":post,
                                      "assumptions":["Use only synthetic text and the isolated local test environment"]})
    return c,actions
