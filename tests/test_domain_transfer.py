"""Pure Domain validation tests for Chat transfer payloads."""
import unittest

from kira.domain.transfer import (
    MAX_METADATA_DEPTH,
    TransferError,
    sanitize_transfer_metadata,
)


class ChatTransferDomainTests(unittest.TestCase):
    def test_secret_like_metadata_keys_are_removed_recursively(self):
        value = sanitize_transfer_metadata({
            "source": "test",
            "api_key": "hidden",
            "nested": {"refresh_token": "hidden", "keep": True},
        })
        self.assertEqual(value, {
            "source": "test",
            "nested": {"keep": True},
        })

    def test_non_finite_numbers_and_excessive_nesting_are_rejected(self):
        with self.assertRaises(TransferError):
            sanitize_transfer_metadata({"score": float("inf")})

        nested = "leaf"
        for _ in range(MAX_METADATA_DEPTH + 2):
            nested = {"next": nested}
        with self.assertRaises(TransferError):
            sanitize_transfer_metadata(nested)

    def test_unsupported_metadata_objects_do_not_leak_into_export(self):
        self.assertIsNone(sanitize_transfer_metadata(object()))


if __name__ == "__main__":
    unittest.main()
