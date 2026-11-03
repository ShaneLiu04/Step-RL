"""Real HTTP shop tests (no browser, no mocks)."""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from step_rl.edge.site import PRODUCTS, LocalShopServer
from step_rl.edge.tasks import TASK_BY_ID
from step_rl.edge.verifier import compute_progress


@pytest.fixture(scope="module")
def server():
    srv = LocalShopServer().start()
    yield srv
    srv.stop()


@pytest.fixture()
def client(server):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(path):
        return opener.open(server.base_url + path).read().decode("utf-8")

    def post(path, data):
        body = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            server.base_url + path, data=body, method="POST"
        )
        response = opener.open(request)
        return response.read().decode("utf-8")

    def state():
        return json.loads(get("/api/state"))

    return get, post, state, server


def test_catalog_is_real():
    assert set(PRODUCTS) == {"p1", "p2", "p3", "p4"}
    assert all(p.price > 0 and p.keywords for p in PRODUCTS.values())


def test_search_updates_server_state(client):
    get, post, state, _ = client
    html = get("/search?q=usb")
    assert "USB-C" in html
    assert state()["query"] == "usb"


def test_add_and_cart(client):
    get, post, state, _ = client
    get("/add/p2?qty=2")
    assert state()["cart"]["p2"] == 2
    html = get("/cart")
    assert "USB-C" in html and "× 2" in html


def test_invalid_quantity_rejected(client):
    get, post, state, server = client
    with pytest.raises(urllib.error.HTTPError):
        get("/add/p1?qty=0")


def test_full_checkout_creates_order(client):
    get, post, state, server = client
    get("/add/p1?qty=1")
    get("/cart")
    get("/checkout")
    post("/place-order", {"name": "Agent", "address": "Shenzhen"})
    st = state()
    assert st["order"] is not None
    assert st["order"]["items"]["p1"] == 1


def test_empty_cart_cannot_checkout(client):
    get, post, state, server = client
    get("/api/reset")
    get("/checkout")
    with pytest.raises(urllib.error.HTTPError):
        post("/place-order", {"name": "Agent", "address": "Shenzhen"})
    assert state()["order"] is None


def test_reset_clears_state(client):
    get, post, state, _ = client
    get("/add/p4?qty=1")
    get("/api/reset")
    st = state()
    assert st["cart"] == {} and st["order"] is None and st["query"] == ""


def test_verifier_progress_matches_real_state(client):
    get, post, state, _ = client
    get("/api/reset")
    task = TASK_BY_ID["sft_add_p1"]
    assert compute_progress(state(), "/", task).progress == 0.0
    get("/search?q=iphone")
    get("/product/p1")
    result = compute_progress(state(), "/", task)
    assert 0 < result.progress < 1
    get("/add/p1?qty=1")
    assert compute_progress(state(), "/", task).success
