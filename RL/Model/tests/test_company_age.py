"""Company must be older than 3 years before labeling."""

from __future__ import annotations

import unittest
from datetime import date

from Model.company_age import add_calendar_years, company_is_old_enough


class CompanyAgeTests(unittest.TestCase):
    def test_add_years_rolls_leap_day(self):
        self.assertEqual(add_calendar_years(date(2016, 2, 29), 3), date(2019, 2, 28))

    def test_ready_strictly_after_three_years(self):
        first = date(2015, 2, 2)
        self.assertFalse(company_is_old_enough(first, date(2018, 2, 2)))
        self.assertTrue(company_is_old_enough(first, date(2018, 2, 3)))

    def test_missing_dates_are_blocked(self):
        self.assertFalse(company_is_old_enough(None, date(2020, 1, 1)))
        self.assertFalse(company_is_old_enough(date(2015, 1, 1), None))


if __name__ == "__main__":
    unittest.main()
