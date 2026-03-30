import tempfile
import unittest

from hedge_strategy_v1.app.config import load_config
from hedge_strategy_v1.app.executor_stub import ExecutionStub
from hedge_strategy_v1.app.schema import parse_webhook_payload
from hedge_strategy_v1.app.signal_engine import decide_action
from hedge_strategy_v1.app.state_store import StateStore


class SignalFlowTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db")
        self.config.db_path = self.tmp.name
        self.store = StateStore(self.config)
        self.store.bootstrap_symbols(self.config)
        self.executor = ExecutionStub(self.store)

    def tearDown(self):
        self.tmp.close()

    def test_main_then_hedge(self):
        state = self.store.get_symbol_state("BTCUSDT.P")
        main_payload = parse_webhook_payload("buy,BTCUSDT.P,1,67000,regime=bull,role=main")
        main_plan = decide_action(main_payload, state, self.config)
        self.assertTrue(main_plan.accepted)
        state = self.executor.apply(main_plan)
        self.assertEqual(state["main_side"], "long")

        hedge_payload = parse_webhook_payload("sell,BTCUSDT.P,0.25,66800,regime=bull,role=hedge,hedge=0.25")
        hedge_plan = decide_action(hedge_payload, state, self.config)
        self.assertTrue(hedge_plan.accepted)
        state = self.executor.apply(hedge_plan)
        self.assertEqual(state["hedge_side"], "short")
        self.assertAlmostEqual(state["hedge_qty"], 0.25)


if __name__ == "__main__":
    unittest.main()

