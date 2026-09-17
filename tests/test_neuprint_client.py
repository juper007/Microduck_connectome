import contextlib
import hashlib
import io
import json
import os
import traceback
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from microduck_connectome import neuprint_client as nc


SENTINEL = "test-only-secret-never-print"
SHA = "a" * 40


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {nc.CREDENTIAL_ENV: SENTINEL})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.factory = patch.object(nc, "build_opener")
        self.open_factory = self.factory.start()
        self.addCleanup(self.factory.stop)
        self.opener = self.open_factory.return_value
        self.response = self.opener.open.return_value.__enter__.return_value
        self.response.status = 200
        self.response.read.return_value = b'{"columns":["bodyId"],"data":[[523769],[10360]]}'

    def assert_safe_failure(self, expected):
        try:
            nc.NeuprintClient().fetch_dna02()
        except nc.NeuprintError as error:
            self.assertIn(expected, str(error))
            self.assertNotIn(SENTINEL, repr(error))
            self.assertNotIn(SENTINEL, traceback.format_exc())
            self.assertIsNone(error.__context__)
            self.assertIsNone(error.__cause__)
        else:
            self.fail("Expected a safe failure")

    def test_pinned_request_and_deterministic_result(self):
        client = nc.NeuprintClient(timeout_seconds=3.5)
        result = client.fetch_dna02()
        self.assertEqual(result.body_ids, (10360, 523769))
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, nc.ENDPOINT + "/api/custom/custom")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"dataset": nc.DATASET, "cypher": nc.QUERY})
        self.assertEqual(request.get_header("Authorization"), "Bearer " + SENTINEL)
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 3.5})
        self.response.read.assert_called_once_with(nc.MAX_RESPONSE_BYTES + 1)
        self.opener.open.return_value.__exit__.assert_called_once()
        self.assertNotIn(SENTINEL, repr(client))
        self.assertNotIn(SENTINEL, repr(vars(client)))
        self.assertNotIn(SENTINEL, repr(result))

    def test_provenance_hash_and_order_are_stable(self):
        first = nc.NeuprintClient().fetch_dna02().provenance(code_commit=SHA)
        self.response.read.return_value = b'{"columns":["bodyId"],"data":[[10360],[523769]]}'
        second = nc.NeuprintClient().fetch_dna02().provenance(code_commit=SHA)
        self.assertEqual(first["body_id_set_hash"], hashlib.sha256(b"[10360,523769]").hexdigest())
        first.pop("created_utc")
        second.pop("created_utc")
        self.assertEqual(first, second)
        self.assertEqual(first["dataset"], "male-cns:v1.0")
        self.assertEqual(first["extraction_tool_version"], SHA)
        self.assertNotIn(SENTINEL, json.dumps(first))

    def test_bad_commit_is_rejected(self):
        for value in (None, "main", "A" * 40, SENTINEL):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "full lowercase"):
                nc.NeuprintClient().fetch_dna02().provenance(code_commit=value)

    def test_invalid_timeouts(self):
        for value in (0, -1, True, None, "20", float("nan"), float("inf"), 10**1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                nc.NeuprintClient(timeout_seconds=value)
        self.opener.open.assert_not_called()

    def test_missing_or_invalid_credentials_never_connect(self):
        for token in ("", "Bearer token", "token\n", "token\r", "é"):
            with self.subTest(token=token), patch.dict(os.environ, {nc.CREDENTIAL_ENV: token}):
                self.assert_safe_failure("Missing or invalid")
        self.opener.open.assert_not_called()

    def test_http_failures_are_sanitized(self):
        for code, message in ((401, "authorization"), (403, "authorization"),
                              (302, "redirect"), (307, "redirect"), (500, "HTTP")):
            with self.subTest(code=code):
                self.opener.open.side_effect = HTTPError(
                    "https://invalid/" + SENTINEL, code, SENTINEL, {}, io.BytesIO(SENTINEL.encode()))
                self.assert_safe_failure(message)

    def test_network_and_timeout_failures_are_sanitized(self):
        for error in (URLError(SENTINEL), TimeoutError(SENTINEL), OSError(SENTINEL)):
            with self.subTest(error=type(error)):
                self.opener.open.side_effect = error
                self.assert_safe_failure("network")

    def test_response_read_failure_is_sanitized(self):
        self.response.read.side_effect = OSError(SENTINEL)
        self.assert_safe_failure("network")

    def test_unexpected_status_is_rejected(self):
        self.response.status = 204
        self.assert_safe_failure("HTTP status")
        self.response.read.assert_not_called()

    def test_redirects_are_never_followed(self):
        nc.NeuprintClient().fetch_dna02()
        handler = self.open_factory.call_args.args[0]
        for destination in (nc.ENDPOINT + "/elsewhere", "https://untrusted.invalid", "http://neuprint.janelia.org"):
            with self.subTest(destination=destination):
                self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, destination))

    def test_response_size_is_bounded(self):
        self.response.read.return_value = b" " * (nc.MAX_RESPONSE_BYTES + 1)
        self.assert_safe_failure("size limit")

    def test_malformed_json_is_sanitized(self):
        for value in (SENTINEL.encode(), b"\xff", b"[" * 2000):
            with self.subTest(value=value[:20]):
                self.response.read.return_value = value
                self.assert_safe_failure("malformed JSON")

    def test_schema_boundaries(self):
        cases = [None, [], {}, {"columns": ["wrong"], "data": [[1]]},
                 {"columns": ["bodyId"], "data": []}, {"columns": ["bodyId"], "data": {}}]
        cases += [{"columns": ["bodyId"], "data": rows} for rows in
                  ([None], [1], [[]], [[1, 2]], [[True]], [[0]], [[-1]], [[1.5]], [["1"]], [[1], [1]])]
        for payload in cases:
            with self.subTest(payload=payload):
                self.response.read.return_value = json.dumps(payload).encode()
                self.assert_safe_failure("neuPrint returned")

    def test_cli_returns_safe_verified_evidence(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(nc.main(["--code-commit", SHA]), 0)
        evidence = json.loads(output.getvalue())
        self.assertTrue(evidence["expected_result_verified"])
        self.assertEqual(evidence["body_ids"], [10360, 523769])
        self.assertNotIn(SENTINEL, output.getvalue())

    def test_cli_rejects_drift_without_printing_response(self):
        self.response.read.return_value = b'{"columns":["bodyId"],"data":[[123]]}'
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(nc.main(["--code-commit", SHA]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("differs", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
