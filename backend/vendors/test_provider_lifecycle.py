"""Owned provider cleanup coverage for the upstream explorer."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from .upstream import OperationSpec, _execute_cint, _execute_rfg


def operation(code, endpoint=""):
    return OperationSpec(
        code=code,
        label=code,
        description=code,
        endpoint=endpoint,
        documentation_url="https://docs.example.test",
    )


class ExplorerProviderLifecycleTests(SimpleTestCase):
    @patch("vendors.upstream.get_provider")
    def test_rfg_provider_closes_without_masking_result(self, get_provider):
        provider = get_provider.return_value
        provider.test_connection.return_value = {"ok": True}
        provider.close.side_effect = RuntimeError("close failed")
        integration = SimpleNamespace(config={})

        result = _execute_rfg(integration, operation("test"), {})

        self.assertEqual(result, {"ok": True})
        provider.close.assert_called_once_with()

    @patch("vendors.upstream.get_provider")
    def test_cint_provider_closes_without_masking_result(self, get_provider):
        provider = get_provider.return_value
        provider.explorer_read.return_value = {"ok": True}
        provider.close.side_effect = RuntimeError("close failed")
        integration = SimpleNamespace(supplier_code="0050")

        result = _execute_cint(integration, operation("definitions", "/definitions"), {})

        self.assertEqual(result, {"ok": True})
        provider.close.assert_called_once_with()
