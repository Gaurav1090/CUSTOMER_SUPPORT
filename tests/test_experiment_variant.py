import unittest

from utils.ops import assign_experiment_variant


class AssignExperimentVariantTests(unittest.TestCase):
    def test_same_session_id_always_gets_same_variant(self):
        first = assign_experiment_variant("session-abc-123")
        second = assign_experiment_variant("session-abc-123")
        self.assertEqual(first, second)

    def test_empty_session_id_is_control(self):
        self.assertEqual(assign_experiment_variant(""), "control")
        self.assertEqual(assign_experiment_variant(None), "control")

    def test_result_is_always_one_of_the_two_variants(self):
        for i in range(200):
            self.assertIn(assign_experiment_variant(f"session-{i}"), ("control", "treatment"))

    def test_split_is_roughly_even_across_many_sessions(self):
        """Not a statistical rigor test -- just a smoke check that the hash
        isn't secretly constant or wildly skewed (e.g. always "control")."""
        treatment_count = sum(
            1 for i in range(2000) if assign_experiment_variant(f"session-{i}") == "treatment"
        )
        self.assertGreater(treatment_count, 800)
        self.assertLess(treatment_count, 1200)

    def test_treatment_percent_zero_is_always_control(self):
        for i in range(50):
            self.assertEqual(assign_experiment_variant(f"session-{i}", treatment_percent=0), "control")

    def test_treatment_percent_hundred_is_always_treatment(self):
        for i in range(50):
            self.assertEqual(assign_experiment_variant(f"session-{i}", treatment_percent=100), "treatment")


if __name__ == "__main__":
    unittest.main()
