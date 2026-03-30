import tempfile
import unittest

from hedge_strategy_v1.app.config import load_config
from hedge_strategy_v1.app.risk_manager import assess_risk
from hedge_strategy_v1.app.schema import parse_webhook_payload
from hedge_strategy_v1.app.state_store import StateStore


class RiskManagerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db")
        self.config.db_path = self.tmp.name
        self.store = StateStore(self.config)
        self.store.bootstrap_symbols(self.config)

    def tearDown(self):
        self.tmp.close()

    def test_reject_neutral_main_entry(self):
        payload = parse_webhook_payload("buy,BTCUSDT.P,1,67000,regime=neutral,role=main")
        state = self.store.get_symbol_state("BTCUSDT.P")
        decision = assess_risk(payload, state, self.config)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "neutral_regime")

    def test_reject_hedge_without_main(self):
        payload = parse_webhook_payload("sell,BTCUSDT.P,0.25,66800,regime=bull,role=hedge,hedge=0.25")
        state = self.store.get_symbol_state("BTCUSDT.P")
        decision = assess_risk(payload, state, self.config)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "missing_main_position")


if __name__ == "__main__":
    unittest.main()

