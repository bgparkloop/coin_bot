import tempfile
import unittest

from hedge_strategy_v1.app.config import load_config
from hedge_strategy_v1.app.state_store import StateStore
from hedge_strategy_v1.app.telegram_bot import TelegramCommandHandler


class TelegramCommandTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db")
        self.config.db_path = self.tmp.name
        self.store = StateStore(self.config)
        self.store.bootstrap_symbols(self.config)
        self.handler = TelegramCommandHandler(self.store, self.config)

    def tearDown(self):
        self.tmp.close()

    def test_trade_toggle(self):
        msg = self.handler.handle_command("trade 0")
        self.assertIn("중지", msg)
        self.assertFalse(self.store.get_trading_enabled())

    def test_set_leverage(self):
        msg = self.handler.handle_command("set BTCUSDT.P lev 4")
        self.assertIn("4.00", msg)
        state = self.store.get_symbol_state("BTCUSDT.P")
        self.assertEqual(state["max_leverage"], 4.0)


if __name__ == "__main__":
    unittest.main()
