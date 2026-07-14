from fastapi.testclient import TestClient


def test_member_crud(client: TestClient, auth_headers: dict[str, str]):
    create = client.post(
        "/api/members",
        headers=auth_headers,
        json={
            "name": "자동테스트 회원",
            "phone": "010-0000-0000",
            "grade": "일반",
            "memo": "pytest",
            "status": "활성",
            "priority": "보통",
            "source": "자동테스트",
            "preferred_count": 10,
            "contract_months": 12,
        },
    )
    assert create.status_code == 200, create.text
    member_id = int(create.json()["id"])

    listing = client.get("/api/members", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    assert str(member_id) in listing.text
    assert "자동테스트 회원" in listing.text

    update = client.put(
        f"/api/members/{member_id}",
        headers=auth_headers,
        json={
            "name": "자동테스트 회원 수정",
            "phone": "010-1111-1111",
            "grade": "2등",
            "memo": "updated",
            "status": "활성",
            "priority": "높음",
            "source": "자동테스트",
            "preferred_count": 12,
            "contract_months": 12,
        },
    )
    assert update.status_code == 200, update.text

    detail = client.get(f"/api/members/{member_id}/detail", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert "자동테스트 회원 수정" in detail.text

    delete = client.delete(f"/api/members/{member_id}", headers=auth_headers)
    assert delete.status_code == 200, delete.text
    assert delete.json()["ok"] is True
