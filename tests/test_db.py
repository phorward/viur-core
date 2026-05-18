# TODO: Add more tests from https://github.com/viur-framework/viur-datastore/tree/master/tests

from abstract import ViURTestCase


class TestDb(ViURTestCase):
    def test_key_init(self) -> None:
        from viur.core import db
        key = db.Key("viur", 42)
        self.assertIsInstance(key.id, int)
        self.assertEqual(key.id, 42)
        self.assertIsNone(key.name)
        self.assertIsNone(key.parent)

        key = db.Key("viur", "1337")
        self.assertIsInstance(key.id, int)
        self.assertEqual(key.id, 1337)
        self.assertIsNone(key.name)
        self.assertIsNone(key.parent)

        key = db.Key("viur", "foo")
        self.assertEqual(key.name, "foo")
        self.assertIsNone(key.id)
        self.assertIsNone(key.parent)

        parent_key = db.Key("viur", "foo")
        key = db.Key("viur", "bar", parent=parent_key)
        self.assertEqual(key.name, "bar")
        self.assertEqual(key.parent, parent_key)


class TestKeyHelper(ViURTestCase):
    def setUp(self):
        super().setUp()
        from viur.core import db
        self.db = db

    # --- int input ---

    def test_int_positive_returns_key(self) -> None:
        key = self.db.key_helper(42, "myKind")
        self.assertIsInstance(key, self.db.Key)
        self.assertEqual(key.kind, "myKind")
        self.assertEqual(key.id, 42)

    def test_int_zero_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.key_helper(0, "myKind")

    def test_int_negative_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.key_helper(-1, "myKind")

    def test_int_negative_large_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.key_helper(-999, "myKind")

    # --- str input ---

    def test_str_name_returns_key(self) -> None:
        key = self.db.key_helper("hello", "myKind")
        self.assertIsInstance(key, self.db.Key)
        self.assertEqual(key.kind, "myKind")
        self.assertEqual(key.name, "hello")

    def test_str_numeric_returns_int_key(self) -> None:
        key = self.db.key_helper("42", "myKind")
        self.assertIsInstance(key, self.db.Key)
        self.assertEqual(key.kind, "myKind")
        self.assertEqual(key.id, 42)

    def test_str_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.key_helper("", "myKind")

    def test_str_whitespace_only_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.key_helper("   ", "myKind")

    def test_str_tab_only_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.key_helper("\t", "myKind")

    def test_str_encoded_key_same_kind_returns_key(self) -> None:
        original = self.db.Key("myKind", 123)
        encoded = str(original)
        key = self.db.key_helper(encoded, "myKind")
        self.assertEqual(key.kind, "myKind")
        self.assertEqual(key.id, 123)

    def test_str_encoded_key_kind_mismatch_raises(self) -> None:
        original = self.db.Key("otherKind", 123)
        encoded = str(original)
        with self.assertRaises(ValueError):
            self.db.key_helper(encoded, "myKind")

    def test_str_encoded_key_adjust_kind(self) -> None:
        original = self.db.Key("otherKind", 123)
        encoded = str(original)
        key = self.db.key_helper(encoded, "myKind", adjust_kind=True)
        self.assertEqual(key.kind, "myKind")
        self.assertEqual(key.id, 123)

    # --- Key input ---

    def test_key_same_kind_returns_key(self) -> None:
        in_key = self.db.Key("myKind", 42)
        result = self.db.key_helper(in_key, "myKind")
        self.assertIs(result, in_key)

    def test_key_kind_mismatch_raises(self) -> None:
        in_key = self.db.Key("otherKind", 42)
        with self.assertRaises(ValueError):
            self.db.key_helper(in_key, "myKind")

    def test_key_additional_allowed_kind_accepted(self) -> None:
        in_key = self.db.Key("aliasKind", 42)
        result = self.db.key_helper(in_key, "myKind", additional_allowed_kinds=["aliasKind"])
        self.assertIs(result, in_key)

    def test_key_kind_mismatch_adjust_kind(self) -> None:
        in_key = self.db.Key("otherKind", 42)
        result = self.db.key_helper(in_key, "myKind", adjust_kind=True)
        self.assertEqual(result.kind, "myKind")
        self.assertEqual(result.id_or_name, 42)

    def test_key_kind_mismatch_adjust_kind_preserves_parent(self) -> None:
        parent = self.db.Key("parentKind", 1)
        in_key = self.db.Key("otherKind", 42, parent=parent)
        result = self.db.key_helper(in_key, "myKind", adjust_kind=True)
        self.assertEqual(result.kind, "myKind")
        self.assertEqual(result.id_or_name, 42)
        self.assertEqual(result.parent, parent)

    # --- unsupported type ---

    def test_unsupported_type_raises(self) -> None:
        with self.assertRaises(NotImplementedError):
            self.db.key_helper(3.14, "myKind")
