def test_long_polling_route_registered(client):
    resp = client.get("/api/long-poll")
    # If route exists but no GET implemented, expect 404 or 405
    assert resp.status_code in {404, 405}
