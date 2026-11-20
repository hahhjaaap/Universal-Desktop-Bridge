"""Read-only Chrome DOM scan retains output while limiting style checks.

Only synthetic DOM nodes are created inside an isolated Node.js subprocess.
No real browser, network, personal tabs, local profiles or owner grants.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from udb.browser_dom import DOM_TRAVERSAL_SCRIPT
from udb.browser_observation import _READ_SCRIPT, _SNAPSHOT_SCRIPT

_BOUNDED = """  const visibleElements=[];
  for(const element of all){
    if(!visible(element))continue;
    visibleElements.push(element);
    if(visibleElements.length>120)break;
  }"""
_OLD = "  const visibleElements=all.filter(visible);"


def _js_output(script, count, *, hide_every_third=False, secret_first=False):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable for pure synthetic DOM comparison")
    source = script.replace("__TRAVERSAL__", DOM_TRAVERSAL_SCRIPT)
    program = f"""
const count={count}, hideThird={json.dumps(hide_every_third)}, secretFirst={json.dumps(secret_first)};
let styleCalls=0;
const items=Array.from({{length:count}},(_,i)=>({{
  tagName:"BUTTON",id:"id-"+i,name:"",autocomplete:"off",
  textContent:"button "+i,innerText:"button "+i,value:i===0?"secret-demo-value":"",
  readOnly:false,parentElement:null,_hidden:hideThird&&i%3===0,_secret:secretFirst&&i===0,
  hasAttribute(){{return false;}},
  getAttribute(key){{return key==="type"&&this._secret?"password":null;}},
  matches(){{return false;}},
  getBoundingClientRect(){{return {{width:20,height:10}};}}
}}));
const NodeFilter={{SHOW_ELEMENT:1}};
const document={{
  title:"Synthetic local form",body:{{innerText:"safe synthetic page"}},
  children:[],createTreeWalker(){{return {{nextNode(){{return null;}}}};}},
  querySelectorAll(){{return items;}}
}};
const location={{origin:"https://example.org",pathname:"/synthetic"}};
function getComputedStyle(e){{
  styleCalls++;
  return {{display:e._hidden?"none":"block",visibility:"visible",opacity:"1"}};
}}
const result={source};
process.stdout.write(JSON.stringify({{result,styleCalls}}));
"""
    proc = subprocess.run(
        [node, "-e", program],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(proc.stdout)


def test_bounded_read_has_same_elements_and_truncation_as_previous_script():
    assert _READ_SCRIPT.count(_BOUNDED) == 1
    old = _READ_SCRIPT.replace(_BOUNDED, _OLD)
    for count, hidden, secret in (
        (0, False, False),
        (120, False, False),
        (121, False, False),
        (5000, False, True),
        (5000, True, False),
        (10000, False, False),
    ):
        new = _js_output(_READ_SCRIPT, count, hide_every_third=hidden, secret_first=secret)
        previous = _js_output(old, count, hide_every_third=hidden, secret_first=secret)
        assert new["result"] == previous["result"], (
            f"Read output changed for count={count}, hidden={hidden}"
        )
        assert new["styleCalls"] <= previous["styleCalls"]
        if count >= 5000:
            assert new["styleCalls"] <= 182
            assert previous["styleCalls"] == count
        if secret:
            assert "secret-demo-value" not in json.dumps(new["result"])


def test_snapshot_still_counts_all_visible_elements_without_cutoff():
    assert "const visibleElements=all.filter(visible);" in _SNAPSHOT_SCRIPT
    assert _READ_SCRIPT.count("if(visibleElements.length>120)break;") == 1
    assert "elements_truncated:visibleElements.length>120||traversalTruncated" in (
        _READ_SCRIPT
    )
