from fastapi.testclient import TestClient

from examples.fastapi_retail.app import app


def test_fastapi_example_real_http_contract() -> None:
    with TestClient(app) as client:
        response = client.post("/ask", json={"query": {"text": "services for retailers"}})
        response.raise_for_status()
        payload = response.json()
        assert payload["results"]
        assert payload["results"][0]["@type"] == "Service"
        assert "schema_object" not in payload["results"][0]


def test_provider_fastapi_openapi_exposes_editable_nlweb_request_schemas():
    from fastapi import FastAPI
    from nlweb_widget import NLWebWidget
    from nlweb_widget.integrations.fastapi_integration import mount_fastapi_nlweb

    app = mount_fastapi_nlweb(FastAPI(), NLWebWidget())
    schema = app.openapi()
    ask_body = schema["paths"]["/ask"]["post"]["requestBody"]
    mcp_body = schema["paths"]["/mcp"]["post"]["requestBody"]
    ask_media = ask_body["content"]["application/json"]
    mcp_media = mcp_body["content"]["application/json"]
    assert ask_media["schema"]["properties"]["query"]["required"] == ["text"]
    assert ask_media["examples"]["nlwebAsk"]["value"]["meta"]["version"] == "0.55"
    assert mcp_media["schema"]["properties"]["jsonrpc"]["enum"] == ["2.0"]
    assert mcp_media["examples"]["mcpAsk"]["value"]["method"] == "tools/call"
