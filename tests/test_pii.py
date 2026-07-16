import unittest

from utils.pii import redact_pii


class RedactPiiTests(unittest.TestCase):
    def test_none_and_empty_pass_through_unchanged(self):
        self.assertIsNone(redact_pii(None))
        self.assertEqual(redact_pii(""), "")

    def test_redacts_email(self):
        result = redact_pii("Contact me at john.doe@example.com for details.")
        self.assertIn("[REDACTED_EMAIL]", result)
        self.assertNotIn("john.doe@example.com", result)

    def test_redacts_phone_number(self):
        result = redact_pii("Call me at 555-123-4567 tomorrow.")
        self.assertIn("[REDACTED_PHONE]", result)
        self.assertNotIn("555-123-4567", result)

    def test_redacts_card_like_number(self):
        result = redact_pii("My card is 4111 1111 1111 1111, please refund it.")
        self.assertIn("[REDACTED_CARD]", result)
        self.assertNotIn("4111 1111 1111 1111", result)

    def test_redacts_person_name_via_ner(self):
        result = redact_pii("I bought this for my friend Sarah Johnson.")
        self.assertIn("[REDACTED_PERSON]", result)
        self.assertNotIn("Sarah Johnson", result)

    def test_redacts_location_via_ner(self):
        result = redact_pii("Shipped to Mumbai last week.")
        self.assertIn("[REDACTED_LOCATION]", result)
        self.assertNotIn("Mumbai", result)

    def test_does_not_flag_product_names_or_ratings(self):
        """Regression guard: this app's own review/product data is full of
        numeric-ish strings (ratings, model numbers) that must not trip the
        phone/card regexes -- a false positive here would corrupt real
        product data on every ingest."""
        text = "The Boat Rockerz 235v2 has a rating of 4.5 out of 5."
        self.assertEqual(redact_pii(text), text)

    def test_does_not_flag_ordinary_review_text(self):
        text = "Great bass and battery life, lasted 2 days on a single charge."
        self.assertEqual(redact_pii(text), text)


if __name__ == "__main__":
    unittest.main()
