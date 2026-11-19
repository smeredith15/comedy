import json

from conftest import FakeHttp

from specials import check
from specials.http import HttpError
from specials.sources import redact


def raiser(status, body):
    def f(params):
        raise HttpError(status, "https://x", json.dumps(body))
    return f


def test_youtube_ok_and_key_in_header_not_url():
    seen = {}

    class H(FakeHttp):
        def get_json(self, url, params=None, headers=None):
            seen.setdefault("headers", headers)
            seen.setdefault("params", params)
            return super().get_json(url, params, headers)
    http = H({"/youtube/v3/videos": {"items": [{"id": "x"}]}, "/youtube/v3/channels": {"items": [{"id": "c"}]}})
    assert check.check_youtube(http, {"YOUTUBE_API_KEY": "AIzaSECRETSECRET"})[0] == "ok"
    assert seen["headers"] == {"X-goog-api-key": "AIzaSECRETSECRET"}
    assert "key" not in seen["params"]


def test_youtube_api_not_enabled_explained():
    body = {"error": {"code": 403, "status": "PERMISSION_DENIED",
                      "details": [{"reason": "SERVICE_DISABLED"}]}}
    http = FakeHttp({"/youtube/v3/videos": raiser(403, body)})
    status, msg = check.check_youtube(http, {"YOUTUBE_API_KEY": "AIzaSECRETSECRET"})
    assert status == "fail" and "Enable" in msg


def test_youtube_bad_key_explained():
    body = {"error": {"code": 400, "errors": [{"reason": "badRequest"}], "details": [{"reason": "API_KEY_INVALID"}]}}
    http = FakeHttp({"/youtube/v3/videos": raiser(400, body)})
    assert "key is wrong" in check.check_youtube(http, {"YOUTUBE_API_KEY": "AIzaSECRETSECRET"})[1]


def test_tmdb_short_key_hint():
    http = FakeHttp({"/3/authentication": raiser(401, {})})
    status, msg = check.check_tmdb(http, {"TMDB_READ_TOKEN": "abc123shortkey"})
    assert status == "fail" and "API Read Access Token" in msg


def test_redact():
    assert redact("GET /v?key=AIzaSECRETSECRET failed", {"YOUTUBE_API_KEY": "AIzaSECRETSECRET"}) == "GET /v?key=*** failed"
