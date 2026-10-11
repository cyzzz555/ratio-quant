"""Offline reference contract checks; run python -m unittest discover -s reference/tests -v"""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from risk_math import (
    initial_principal_loss_pct, high_water_drawdown_pct, risk_budget,
    linear_contract_qty, linear_notional, theoretical_initial_margin,
    gross_effective_leverage, leverage_preference_check, directional_stop_precedes_liquidation,
    floor_to_step, dec
)


class RiskMathTests(unittest.TestCase):
    def test_20x_does_not_multiply_planned_loss(self):
        budget = risk_budget(D("1000"), D("1"))
        qty = linear_contract_qty(budget=budget, entry=D("100"), stop=D("98"), multiplier=D("1"), step=D("1"))
        self.assertEqual(qty, D("5"))
        self.assertEqual(linear_notional(qty, D("100")), D("500"))
        self.assertEqual(theoretical_initial_margin(D("500"), 20), D("25"))

    def test_trade_cost_shrinks_quantity(self):
        qty = linear_contract_qty(budget=D("10"), entry=D("100"), stop=D("98"), multiplier=D("1"), step=D("0.1"), extra_loss_per_unit=D("0.5"))
        self.assertEqual(qty, D("4"))

    def test_floor_never_rounds_up(self):
        self.assertEqual(floor_to_step(D("1.999"), D("0.01")), D("1.99"))

    def test_principal_loss_flow_adjusted(self):
        self.assertEqual(initial_principal_loss_pct(D("1000"), D("650"), D("100")), D("45"))

    def test_peak_drawdown_independent_from_principal_loss(self):
        self.assertEqual(initial_principal_loss_pct(D("1000"), D("1000")), D("0"))
        self.assertAlmostEqual(float(high_water_drawdown_pct(D("1300"), D("1000"))), 23.0769230769, 8)

    def test_exchange_leverage_approval(self):
        self.assertEqual(leverage_preference_check(26, 50), "REJECT_USER_HARD_CAP")
        self.assertEqual(leverage_preference_check(25, 20), "REJECT_EXCHANGE_OR_ACCOUNT_MAX")
        self.assertEqual(leverage_preference_check(25, None), "BLOCK_UNVERIFIED_ACCOUNT_LEVERAGE")
        self.assertEqual(leverage_preference_check(25, 25), "PENDING_SPECIAL_APPROVAL_RESEARCH_ONLY")
        self.assertEqual(leverage_preference_check(20, 20), "PREFERRED_RANGE_NOT_TRADE_AUTHORIZATION")

    def test_effective_gross_leverage(self):
        self.assertEqual(gross_effective_leverage(D("2500"), D("1000")), D("2.5"))

    def test_liquidation_signs(self):
        self.assertTrue(directional_stop_precedes_liquidation("LONG", D("100"), D("98"), D("96")))
        self.assertFalse(directional_stop_precedes_liquidation("LONG", D("100"), D("94"), D("96")))
        self.assertTrue(directional_stop_precedes_liquidation("SHORT", D("100"), D("102"), D("105")))
        self.assertFalse(directional_stop_precedes_liquidation("SHORT", D("100"), D("106"), D("105")))

    def test_float_rejected(self):
        with self.assertRaises(TypeError):
            dec(0.1)


if __name__ == "__main__":
    unittest.main()
