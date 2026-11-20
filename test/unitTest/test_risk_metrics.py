"""Risk statistics over a stored value series (KAN-27).

These tiles previously showed hardcoded figures, so the rule under test throughout is that a
number appears only when the window really supports it and is null otherwise -- never a zero
standing in for "unknown", which reads as a real measurement.
"""
import unittest

from backend.app.services import risk_metrics


def series(*pairs):
    return [{"date": d, "value": float(v)} for d, v in pairs]


RISE_DIP_RISE = series(
    ("2024-01-02", 100.0),
    ("2024-01-03", 110.0),
    ("2024-01-04", 99.0),
    ("2024-01-05", 120.0),
)


class TestMaxDrawdown(unittest.TestCase):
    def test_the_worst_peak_to_trough_fall_is_measured_from_the_peak(self):
        # Peak 110 then trough 99: 11/110, not 11/120 or 11/100.
        self.assertAlmostEqual(risk_metrics.max_drawdown_pct(RISE_DIP_RISE), 10.0, places=6)

    def test_a_series_that_only_rises_has_a_real_zero_drawdown(self):
        rising = series(("2024-01-02", 100.0), ("2024-01-03", 101.0))
        self.assertEqual(risk_metrics.max_drawdown_pct(rising), 0.0)

    def test_one_point_cannot_show_a_drawdown_so_it_is_null_not_zero(self):
        self.assertIsNone(risk_metrics.max_drawdown_pct(series(("2024-01-02", 100.0))))

    def test_an_empty_series_is_null(self):
        self.assertIsNone(risk_metrics.max_drawdown_pct([]))

    def test_a_later_peak_resets_the_reference(self):
        # 100 -> 90 is 10%; the second fall 200 -> 150 is 25% and must win.
        points = series(
            ("2024-01-02", 100.0),
            ("2024-01-03", 90.0),
            ("2024-01-04", 200.0),
            ("2024-01-05", 150.0),
        )
        self.assertAlmostEqual(risk_metrics.max_drawdown_pct(points), 25.0, places=6)


class TestDailyReturns(unittest.TestCase):
    def test_returns_are_between_consecutive_observations(self):
        self.assertEqual(len(risk_metrics.daily_returns(RISE_DIP_RISE)), 3)
        self.assertAlmostEqual(risk_metrics.daily_returns(RISE_DIP_RISE)[0], 0.10, places=9)

    def test_a_zero_value_cannot_divide_so_that_pair_is_dropped(self):
        points = series(("2024-01-02", 0.0), ("2024-01-03", 50.0), ("2024-01-04", 55.0))
        self.assertEqual([round(r, 4) for r in risk_metrics.daily_returns(points)], [0.1])


class TestAnnualisedVolatility(unittest.TestCase):
    def test_it_annualises_the_sample_deviation_by_root_252(self):
        # Returns +10% then -10%: sample sd = sqrt(0.02), x sqrt(252) = 224.5%.
        points = series(("2024-01-02", 100.0), ("2024-01-03", 110.0), ("2024-01-04", 99.0))
        self.assertAlmostEqual(risk_metrics.annualised_volatility_pct(points), 224.5, places=1)

    def test_a_flat_series_has_a_real_zero_volatility(self):
        flat = series(("2024-01-02", 50.0), ("2024-01-03", 50.0), ("2024-01-04", 50.0))
        self.assertEqual(risk_metrics.annualised_volatility_pct(flat), 0.0)

    def test_two_points_give_one_return_which_cannot_have_a_deviation(self):
        pair = series(("2024-01-02", 100.0), ("2024-01-03", 110.0))
        self.assertIsNone(risk_metrics.annualised_volatility_pct(pair))

    def test_an_empty_series_is_null(self):
        self.assertIsNone(risk_metrics.annualised_volatility_pct([]))


class TestWindow(unittest.TestCase):
    SPAN = series(
        ("2024-01-15", 10.0),
        ("2024-09-15", 20.0),
        ("2024-11-15", 30.0),
        ("2024-12-15", 40.0),
    )

    def test_all_returns_every_point(self):
        self.assertEqual(len(risk_metrics.window(self.SPAN, "ALL")), 4)

    def test_the_cutoff_is_the_last_stored_date_not_today(self):
        # The series ends in 2024, so a window measured from today would be empty.
        self.assertEqual(
            [p["date"] for p in risk_metrics.window(self.SPAN, "1M")], ["2024-11-15", "2024-12-15"]
        )

    def test_the_cutoff_date_itself_is_included(self):
        points = series(("2024-11-15", 1.0), ("2024-12-15", 2.0))
        self.assertEqual(len(risk_metrics.window(points, "1M")), 2)

    def test_longer_windows_reach_further_back(self):
        self.assertEqual(len(risk_metrics.window(self.SPAN, "3M")), 3)
        self.assertEqual(len(risk_metrics.window(self.SPAN, "1Y")), 4)

    def test_an_empty_series_windows_to_nothing(self):
        self.assertEqual(risk_metrics.window([], "1M"), [])


class TestMetricsFor(unittest.TestCase):
    def test_cumulative_return_is_first_to_last_within_the_window(self):
        m = risk_metrics.metrics_for(RISE_DIP_RISE, "ALL")
        self.assertAlmostEqual(m["cumulative_return_pct"], 20.0, places=6)
        self.assertAlmostEqual(m["cumulative_return_gbp"], 20.0, places=6)

    def test_it_reports_the_window_it_actually_measured(self):
        m = risk_metrics.metrics_for(RISE_DIP_RISE, "ALL")
        self.assertEqual((m["start_date"], m["end_date"], m["trading_days"]), ("2024-01-02", "2024-01-05", 4))

    def test_sharpe_is_never_populated_without_a_risk_free_rate(self):
        for timeframe in risk_metrics.TIMEFRAMES:
            self.assertIsNone(risk_metrics.metrics_for(RISE_DIP_RISE, timeframe)["sharpe_ratio"])

    def test_a_single_point_window_reports_no_statistics(self):
        m = risk_metrics.metrics_for(series(("2024-01-02", 100.0)), "ALL")
        self.assertEqual(m["trading_days"], 1)
        for field in ("cumulative_return_pct", "cumulative_return_gbp", "max_drawdown_pct",
                      "annualised_volatility_pct"):
            self.assertIsNone(m[field], field)

    def test_an_empty_series_reports_no_dates_and_no_statistics(self):
        m = risk_metrics.metrics_for([], "ALL")
        self.assertEqual((m["start_date"], m["end_date"], m["trading_days"]), (None, None, 0))
        self.assertIsNone(m["max_drawdown_pct"])

    def test_a_zero_start_has_an_absolute_return_but_no_percentage(self):
        points = series(("2024-01-02", 0.0), ("2024-01-03", 25.0))
        m = risk_metrics.metrics_for(points, "ALL")
        self.assertEqual(m["cumulative_return_gbp"], 25.0)
        self.assertIsNone(m["cumulative_return_pct"])


class TestAllWindows(unittest.TestCase):
    def test_every_timeframe_the_client_offers_is_present(self):
        windows = risk_metrics.all_windows(RISE_DIP_RISE)
        self.assertEqual(sorted(windows), sorted(["1M", "3M", "6M", "1Y", "ALL"]))

    def test_each_window_is_labelled_with_its_own_timeframe(self):
        for timeframe, metrics in risk_metrics.all_windows(RISE_DIP_RISE).items():
            self.assertEqual(metrics["timeframe"], timeframe)


if __name__ == "__main__":
    unittest.main()
