"""Integration test for Price API endpoints and AI Agent intent."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from backend.api.server import create_app

mock_blockchain = MagicMock()
mock_blockchain.chain_id = 31337
mock_blockchain.network_manager = MagicMock()

app = create_app(blockchain=mock_blockchain)

mock_simple_price = {
    "ethereum": {
        "usd": 2500.75,
        "usd_24h_change": 1.85,
        "eur": 2300.0,
        "jpy": 380000.0,
        "btc": 0.042,
    }
}

mock_history = {
    "prices": [
        [1730000000000, 2450.0],
        [1730003600000, 2480.0],
        [1730007200000, 2500.75],
    ]
}


def test_integration():
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        def side_effect(url, *args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if "market_chart" in str(url):
                resp.json.return_value = mock_history
            else:
                resp.json.return_value = mock_simple_price
            return resp

        mock_get.side_effect = side_effect

        with TestClient(app) as client:
            # 1. Current price
            resp = client.get("/api/prices/current")
            assert resp.status_code == 200
            data = resp.json()
            assert data["symbol"] == "ETH"
            assert data["price_usd"] == 2500.75
            assert data["change_24h_pct"] == 1.85
            assert data["source"] == "coingecko"
            assert "alerts_triggered" in data
            print("GET /api/prices/current:", data)

            # 2. History 1h, 24h, 7d
            for tf in ["1h", "24h", "7d"]:
                r = client.get(f"/api/prices/history?timeframe={tf}")
                assert r.status_code == 200
                hist = r.json()
                assert hist["timeframe"] == tf
                assert len(hist["prices"]) > 0
                print(f"GET /api/prices/history?timeframe={tf} count:", len(hist["prices"]))

            # Invalid timeframe check
            bad = client.get("/api/prices/history?timeframe=invalid_tf")
            assert bad.status_code == 400

            # 3. Comparison
            comp = client.get("/api/prices/comparison")
            assert comp.status_code == 200
            assert "rates" in comp.json()
            assert comp.json()["rates"]["usd"] == 2500.75
            print("GET /api/prices/comparison:", comp.json())

            # 4. Alerts lifecycle
            post_alert = client.post("/api/prices/alerts", json={"direction": "above", "threshold": 2400.0})
            assert post_alert.status_code == 200
            alert_obj = post_alert.json()
            assert alert_obj["direction"] == "above"
            assert alert_obj["threshold"] == 2400.0
            alert_id = alert_obj["id"]

            list_alerts = client.get("/api/prices/alerts")
            assert list_alerts.status_code == 200
            alerts = list_alerts.json()
            assert any(a["id"] == alert_id for a in alerts)

            # Check alert triggers
            current_with_alert = client.get("/api/prices/current").json()
            # Threshold 2400 < 2500.75, so alert must trigger
            triggered = current_with_alert["alerts_triggered"]
            assert len(triggered) >= 1
            assert any(a["id"] == alert_id for a in triggered)

            # Second call: alert must not re-trigger (fire-once semantics)
            current_second = client.get("/api/prices/current").json()
            assert not any(a["id"] == alert_id for a in current_second["alerts_triggered"])

            del_alert = client.delete(f"/api/prices/alerts/{alert_id}")
            assert del_alert.status_code == 200
            assert del_alert.json()["status"] == "success"
            print("Alerts lifecycle tested successfully.")

            # 5. Agent Chat: Price query
            chat_resp = client.post("/api/chat", json={
                "query": "Giá ETH hiện tại thế nào?",
                "wallet_address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            })
            assert chat_resp.status_code == 200
            res = chat_resp.json()
            assert res["intent"] == "get_crypto_price"
            assert "ETH" in res["reply"]
            assert "$2,500.75" in res["reply"]
            assert "[CHART:ETH:" in res["reply"]
            print("\nAgent Price reply:\n", res["reply"])

            # 6. Agent Chat: Chainlink Oracle query
            chat_chainlink = client.post("/api/chat", json={
                "query": "Kiểm tra giá ETH từ Chainlink oracle",
                "wallet_address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            })
            assert chat_chainlink.status_code == 200
            cl_res = chat_chainlink.json()
            assert cl_res["intent"] == "get_crypto_price"
            print("\nAgent Chainlink reply:\n", cl_res["reply"])


if __name__ == "__main__":
    test_integration()
    print("\n================ ALL INTEGRATION TESTS PASSED! ================")
