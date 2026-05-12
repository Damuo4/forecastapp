import httpx

from sec_client import SecEdgarClient


def test_sec_client_sends_user_agent_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("User-Agent") == "Test App tester@example.com"
        assert request.headers.get("Accept-Encoding") == "gzip, deflate"
        assert request.headers.get("Host") == "data.sec.gov"
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = SecEdgarClient(
        base_url="https://data.sec.gov",
        user_agent="Test App tester@example.com",
        transport=transport,
    )
    payload = client.get_submissions("0000815556")
    assert payload["ok"] is True
