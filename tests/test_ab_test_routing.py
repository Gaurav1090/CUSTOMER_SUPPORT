import os
import unittest
from unittest.mock import patch

import main


class AbTestModelOverrideTests(unittest.TestCase):
    def setUp(self):
        self._original_environ = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_environ)

    def test_control_variant_never_overrides_regardless_of_flag(self):
        with patch.dict(os.environ, {"AB_TEST_ENABLED": "true", "AB_TEST_MODEL_NAME": "some-model"}):
            self.assertIsNone(main._ab_test_model_override("control"))

    def test_treatment_variant_returns_none_when_experiment_disabled(self):
        """Off by default -- AB_TEST_ENABLED must be explicitly "true", so
        this never silently starts spending on a second model."""
        with patch.dict(os.environ, {"AB_TEST_ENABLED": "false", "AB_TEST_MODEL_NAME": "some-model"}):
            self.assertIsNone(main._ab_test_model_override("treatment"))

    def test_treatment_variant_returns_none_when_ab_test_enabled_unset(self):
        with patch.dict(os.environ, {"AB_TEST_MODEL_NAME": "some-model"}, clear=False):
            os.environ.pop("AB_TEST_ENABLED", None)
            self.assertIsNone(main._ab_test_model_override("treatment"))

    def test_treatment_variant_returns_model_when_enabled_and_configured(self):
        with patch.dict(os.environ, {"AB_TEST_ENABLED": "true", "AB_TEST_MODEL_NAME": "llama-3.1-8b-instant"}):
            self.assertEqual(main._ab_test_model_override("treatment"), "llama-3.1-8b-instant")

    def test_treatment_variant_returns_none_when_enabled_but_no_model_configured(self):
        with patch.dict(os.environ, {"AB_TEST_ENABLED": "true"}, clear=False):
            os.environ.pop("AB_TEST_MODEL_NAME", None)
            self.assertIsNone(main._ab_test_model_override("treatment"))


if __name__ == "__main__":
    unittest.main()
