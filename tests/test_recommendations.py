from fastapi.testclient import TestClient


def test_generate_recommendations(client: TestClient, auth_headers: dict[str, str]):
    response = client.post(
        "/api/generate",
        headers=auth_headers,
        json={
            "round_no": 1233,
            "count": 2,
            "mode": "balanced",
            "fixed": "",
            "excluded": "",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    combos = payload.get("sets") or payload.get("combos") or payload.get("numbers") or payload.get("combinations") or payload.get("recommendations")
    assert isinstance(combos, list)
    assert len(combos) == 2
    for combo in combos:
        numbers = combo if isinstance(combo, list) else combo.get("numbers", [])
        assert len(numbers) == 6
        assert len(set(numbers)) == 6
        assert all(1 <= int(number) <= 45 for number in numbers)
