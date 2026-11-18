"""Pure Conversation organization domain validation tests."""
import unittest

from kira.domain.organization import (
    DEFAULT_FOLDER_ID,
    Folder,
    OrganizationError,
    OrganizationFilter,
    Tag,
    contains_control_characters,
    normalize_key,
    normalize_label,
    organization_metadata,
    sanitize_metadata,
)


class OrganizationDomainTests(unittest.TestCase):
    def test_labels_are_nfkc_normalized_and_casefolded(self):
        self.assertEqual(normalize_label("  Ｒｅｓｅａｒｃｈ   Notes  ", "name"), "Research Notes")
        self.assertEqual(normalize_key("Straße", "tag"), "strasse")

    def test_control_characters_and_invalid_labels_are_rejected(self):
        self.assertTrue(contains_control_characters("bad\nlabel"))
        with self.assertRaises(OrganizationError):
            normalize_label("bad\nlabel", "name")
        with self.assertRaises(OrganizationError):
            normalize_label("   ", "name")

    def test_metadata_sanitizer_copies_values_and_rejects_non_finite_numbers(self):
        original = {"nested": {"tags": ["a"]}}
        sanitized = sanitize_metadata(original)
        sanitized["nested"]["tags"].append("b")
        self.assertEqual(original, {"nested": {"tags": ["a"]}})
        with self.assertRaises(OrganizationError):
            sanitize_metadata({"score": float("nan")})

    def test_organization_namespace_is_returned_as_a_defensive_copy(self):
        source = {"external": {"keep": True}, "organization": {"tags": ["urgent"]}}
        value = organization_metadata(source)
        value["tags"].append("new")
        self.assertEqual(source["organization"]["tags"], ["urgent"])

    def test_organization_query_values_are_immutable_contracts(self):
        self.assertEqual(DEFAULT_FOLDER_ID, "inbox")
        self.assertEqual(OrganizationFilter(tags=("work",)).tags, ("work",))
        self.assertEqual(Tag("work", "Work").id, "work")
        self.assertEqual(Folder("inbox", "Inbox").name, "Inbox")


if __name__ == "__main__":
    unittest.main()
