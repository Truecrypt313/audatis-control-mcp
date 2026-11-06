import unittest

import httpx

from audatis_api import AudatisAPI, ConfigurationError, summarize_list


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def handle(request):
            self.calls.append(request)
            return httpx.Response(200, json={
                "data": [{"id": "aaa", "title": "Demo-Asset", "risks": []}],
                "meta": {"page": 1, "per_page": 10, "total": 1, "total_pages": 1},
            })

        self.transport = httpx.MockTransport(handle)
        self.api = AudatisAPI(
            base_url="https://tenant.example.test", token="TEST_ONLY_NOT_REAL",
            client_id=42, transport=self.transport,
        )

    def test_assets_are_readonly_and_tenant_pinned(self):
        out = self.api.tenant_get("assets")
        self.assertEqual(out["data"][0]["title"], "Demo-Asset")
        self.assertEqual(self.calls[0].method, "GET")
        self.assertEqual(self.calls[0].url.path, "/api/v1/clients/42/assets")
        self.assertEqual(self.calls[0].headers["Authorization"], "Bearer TEST_ONLY_NOT_REAL")

    def test_filters_are_allowlisted(self):
        with self.assertRaises(ValueError):
            self.api.tenant_get("assets", other_mandant="43")
        with self.assertRaises(ValueError):
            self.api.tenant_get("../../admin")

    def test_page_limit(self):
        with self.assertRaises(ValueError):
            self.api.tenant_get("assets", per_page=200)

    def test_https_enforced(self):
        with self.assertRaises(ConfigurationError):
            AudatisAPI(base_url="http://tenant.example.test", token="x", client_id=42)
        with self.assertRaises(ConfigurationError):
            AudatisAPI(base_url="https://tenant.example.test/api", token="x", client_id=42)

    def test_summary_drops_unlisted_fields(self):
        result = summarize_list({"data": [{"title": "x", "secret": "not for model"}], "meta": {}}, ("title",))
        self.assertEqual(result, {"data": [{"title": "x"}], "meta": {}})

    def test_no_redirect_followed(self):
        self.api._transport = httpx.MockTransport(lambda _: httpx.Response(302, headers={"Location": "https://evil.example"}))
        with self.assertRaisesRegex(RuntimeError, "302"):
            self.api.tenant_get("assets")


if __name__ == "__main__":
    unittest.main()
