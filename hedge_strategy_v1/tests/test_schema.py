import unittest

from hedge_strategy_v1.app.schema import parse_webhook_payload


class SchemaTests(unittest.TestCase):
    def test_parse_legacy_payload(self):
        payload = parse_webhook_payload("buy,BTCUSDT.P,1,67250")
        self.assertEqual(payload.action, "buy")
        self.assertEqual(payload.symbol, "BTCUSDT.P")
        self.assertEqual(payload.role, "main")
        self.assertEqual(payload.regime, "unknown")

    def test_parse_extended_payload(self):
        payload = parse_webhook_payload(
            "sell,ETHUSDT.P,0.25,3120,regime=bear,role=hedge,hedge=0.25,tf=15"
        )
        self.assertEqual(payload.role, "hedge")
        self.assertEqual(payload.regime, "bear")
        self.assertEqual(payload.hedge_ratio, 0.25)


if __name__ == "__main__":
    unittest.main()

