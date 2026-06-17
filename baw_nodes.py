"""IBM Business Automation Workflow (BAW) nodes (category: BAW).

* **Start Service** — POST {base}/rest/bpm/wle/v1/service/{shortname@name}
  (fixed ``action=start`` ``parts=all`` & ``createTask=false``; input variables in ``params``).
* **Get Service** — GET {base}/rest/bpm/wle/v1/service/{instanceId}
  to retrieve the status/data of a started service instance.

Two auth modes are supported: HTTP basic (username/password) and bearer token.

Docs:
  start: https://www.ibm.com/docs/en/baw/24.0.x?topic=service-post-start
  get:   https://www.ibm.com/docs/en/baw/24.0.x?topic=sm-get
"""

import html
import json
import urllib.parse

import requests

from nbt.core.node_base import BaseNode, NodeError

TIMEOUT = 60

# shared auth inputs for every BAW node
_AUTH = {
    "base_url": "",          # e.g. https://baw-host:9443
    "auth_type": "basic",    # "basic" or "bearer"
    "username": "",          # for basic auth
    "password": "",          # for basic auth
    "token": "",             # for bearer auth
    "verify_ssl": True,      # set False for self-signed certs
}


def _base(inputs):
    base = str(inputs["base_url"]).strip().rstrip("/")
    if not base:
        raise NodeError("base_url is required (e.g. https://baw-host:9443)")
    return base


def _auth(inputs):
    """Return (headers, auth) for the chosen auth mode."""
    headers = {"Accept": "application/json"}
    atype = str(inputs.get("auth_type") or "basic").strip().lower()
    if atype == "bearer":
        token = str(inputs.get("token") or "").strip()
        if not token:
            raise NodeError("token is required for bearer auth")
        headers["Authorization"] = "Bearer " + token
        return headers, None
    user = str(inputs.get("username") or "").strip()
    if not user:
        raise NodeError("username is required for basic auth")
    return headers, (user, str(inputs.get("password") or ""))


def _send(method, url, inputs, ctx, params=None):
    headers, auth = _auth(inputs)
    verify = bool(inputs.get("verify_ssl", True))
    log = ctx.get("log")
    if callable(log):
        log(f"{method} {url}")
    try:
        r = requests.request(method, url, params=params, headers=headers,
                             auth=auth, verify=verify, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise NodeError(f"request failed: {type(e).__name__}: {e}")
    try:
        data = r.json()
    except ValueError:
        data = r.text
    if not r.ok:
        msg = data if isinstance(data, str) else json.dumps(data)[:400]
        raise NodeError(f"BAW {r.status_code}: {msg}")
    return r, data


def _as_model(raw):
    if isinstance(raw, dict):
        return raw
    s = str(raw or "").strip()
    if not s:
        raise NodeError("model is required (service model JSON)")
    try:
        m = json.loads(s)
    except Exception as e:
        raise NodeError(f"model is not valid JSON: {e}")
    if not isinstance(m, dict):
        raise NodeError("model must be a JSON object")
    return m


def _desc_map(data_model):
    """Map name/type -> description from a service model's dataModel.

    Accepts a dict ({name: {description}}) or a list of {name, description}.
    """
    out = {}
    if isinstance(data_model, dict):
        for k, v in data_model.items():
            out[k] = (v.get("description") if isinstance(v, dict) else str(v))
    elif isinstance(data_model, list):
        for item in data_model:
            if isinstance(item, dict):
                key = item.get("name") or item.get("id") or item.get("type")
                if key:
                    out[key] = item.get("description")
    return out


def _var_name(v):
    return (v.get("name") or v.get("variableName") or v.get("id")
            if isinstance(v, dict) else str(v))


def _var_type(v):
    return (v.get("type") or v.get("typeName") or v.get("dataType")
            if isinstance(v, dict) else None)


def _sample_value(v):
    """A representative sample value for a variable, based on its type."""
    if isinstance(v, dict) and v.get("isList"):
        return []
    t = (_var_type(v) or "").lower()
    if t in ("string", "namevaluepair", "text", "xmldocument"):
        return ""
    if t in ("integer", "long", "decimal", "double", "float", "number"):
        return 0
    if t == "boolean":
        return False
    if t in ("date", "time", "datetime", "timestamp"):
        return ""
    return None  # complex / unknown type


def _sample_json(variables):
    out = {}
    for v in variables or []:
        name = _var_name(v)
        if name:
            out[name] = _sample_value(v)
    return out


class BawServiceDoc(BaseNode):
    type_name = "baw_service_doc"
    label = "BAW: Service Doc"
    category = "BAW"
    # `model` is the service model JSON (object or JSON string);
    # `test_name` labels the test row in the output table.
    inputs = {"model": "{}", "test_name": ""}
    outputs = ["html"]

    def run(self, inputs, ctx):
        model = _as_model(inputs["model"])
        name = str(model.get("name") or model.get("serviceName") or "Service")
        description = str(model.get("description") or "")
        inputs_list = model.get("inputs") or []
        outputs_list = model.get("outputs") or []
        descs = _desc_map(model.get("dataModel"))
        test_name = str(inputs.get("test_name") or "")

        def desc_of(v):
            if isinstance(v, dict) and v.get("description"):
                return v["description"]
            return (descs.get(_var_name(v)) or descs.get(_var_type(v) or "")
                    or "")

        def rows(vars_):
            if not vars_:
                return ("<tr><td colspan=\"2\"><em>none</em></td></tr>")
            cells = []
            for v in vars_:
                cells.append(
                    f"<tr><td>{html.escape(str(_var_name(v) or ''))}</td>"
                    f"<td>{html.escape(str(desc_of(v) or ''))}</td></tr>")
            return "".join(cells)

        sample_in = json.dumps(_sample_json(inputs_list), indent=2)
        sample_out = json.dumps(_sample_json(outputs_list), indent=2)

        doc = (
            "<div>\n"
            f"  <h2>{html.escape(name)}</h2>\n"
            f"  <div>{html.escape(description)}</div>\n"
            "  <h3>Inputs</h3>\n"
            "  <table>\n"
            "    <thead><tr><td>Variable Name</td><td>Description</td></tr>"
            "</thead>\n"
            f"    <tbody>{rows(inputs_list)}</tbody>\n"
            "  </table>\n"
            "  <h3>Outputs</h3>\n"
            "  <table>\n"
            "    <thead><tr><td>Variable Name</td><td>Description</td></tr>"
            "</thead>\n"
            f"    <tbody>{rows(outputs_list)}</tbody>\n"
            "  </table>\n"
            "  <h3>Test</h3>\n"
            "  <table>\n"
            "    <thead><tr><td>Test Service Name</td><td>Input JSON</td>"
            "<td>Output JSON</td></tr></thead>\n"
            "    <tbody><tr>"
            f"<td>{html.escape(test_name)}</td>"
            f"<td><pre>{html.escape(sample_in)}</pre></td>"
            f"<td><pre>{html.escape(sample_out)}</pre></td>"
            "</tr></tbody>\n"
            "  </table>\n"
            "</div>"
        )
        return {"html": doc}


class BawStartService(BaseNode):
    type_name = "baw_start_service"
    label = "BAW: Start Service"
    category = "BAW"
    inputs = {**_AUTH,
              "service": "",     # identifier: shortname@service-name
              "params": "{}"}    # JSON object of service input variables
    outputs = ["status_code", "ok", "data"]

    def run(self, inputs, ctx):
        base = _base(inputs)
        service = str(inputs["service"]).strip()
        if not service:
            raise NodeError("service is required (shortname@service-name)")

        raw = inputs["params"]
        params_json = None
        if isinstance(raw, (dict, list)):
            params_json = json.dumps(raw)
        else:
            s = str(raw or "").strip()
            if s:
                try:
                    params_json = json.dumps(json.loads(s))
                except Exception as e:
                    raise NodeError(f"params is not valid JSON: {e}")

        url = (f"{base}/rest/bpm/wle/v1/service/"
               f"{urllib.parse.quote(service, safe='@')}")
        query = {"parts": "all", "createTask": "false","action":"start"}
        if params_json is not None:
            query["params"] = params_json

        r, data = _send("POST", url, inputs, ctx, params=query)
        return {"status_code": r.status_code, "ok": r.ok, "data": data}


class BawGetService(BaseNode):
    type_name = "baw_get_service"
    label = "BAW: Get Service"
    category = "BAW"
    # instance_id is returned by Start Service (the service execution id)
    inputs = {**_AUTH, "instance_id": "", "parts": "all"}
    outputs = ["status_code", "ok", "state", "data"]

    def run(self, inputs, ctx):
        base = _base(inputs)
        instance = str(inputs["instance_id"]).strip()
        if not instance:
            raise NodeError("instance_id is required")
        url = (f"{base}/rest/bpm/wle/v1/service/"
               f"{urllib.parse.quote(instance, safe='')}")
        parts = str(inputs.get("parts") or "all").strip()
        query = {"parts": parts} if parts else None

        r, data = _send("GET", url, inputs, ctx, params=query)
        # surface the execution state when present
        state = None
        if isinstance(data, dict):
            body = data.get("data", data)
            state = (body.get("executionState") or body.get("state")
                     or body.get("status"))
        return {"status_code": r.status_code, "ok": r.ok,
                "state": state, "data": data}
