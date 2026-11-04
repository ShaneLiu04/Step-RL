"""A real, self-contained multi-page shop served over HTTP.

The site keeps authoritative state on the server (search query, cart, form,
orders) and exposes it through ``/api/state``.  An agent interacts with it
through a real browser; nothing here is simulated on the client side.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Product:
    pid: str
    name: str
    price: int
    keywords: tuple[str, ...]

    def matches(self, query: str) -> bool:
        q = query.strip().lower()
        if not q:
            return True
        haystack = " ".join((self.name, *self.keywords)).lower()
        return q in haystack


PRODUCTS: Dict[str, Product] = {
    "p1": Product("p1", "iPhone 15 智能手机", 6999, ("iphone", "手机", "apple")),
    "p2": Product("p2", "USB-C 快充数据线", 59, ("usb", "数据线", "cable", "充电")),
    "p3": Product("p3", "无线充电器", 199, ("无线", "充电器", "charger")),
    "p4": Product("p4", "蓝牙降噪耳机", 399, ("蓝牙", "耳机", "headphone")),
}


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    sid: str
    query: str = ""
    cart: Dict[str, int] = field(default_factory=dict)
    form: Dict[str, str] = field(default_factory=dict)
    order: Optional[Dict[str, object]] = None
    visited: List[str] = field(default_factory=list)

    def reset(self) -> None:
        self.query = ""
        self.cart = {}
        self.form = {}
        self.order = None
        self.visited = []

    def snapshot(self) -> Dict[str, object]:
        return {
            "sid": self.sid,
            "query": self.query,
            "cart": dict(self.cart),
            "form": dict(self.form),
            "order": json.loads(json.dumps(self.order)) if self.order else None,
            "visited": list(self.visited),
        }


class SessionStore:
    def __init__(self) -> None:
        self._states: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def get(self, sid: Optional[str]) -> SessionState:
        with self._lock:
            if not sid or sid not in self._states:
                sid = uuid.uuid4().hex
                self._states[sid] = SessionState(sid=sid)
            return self._states[sid]

    def reset(self, sid: str) -> SessionState:
        with self._lock:
            state = self._states.get(sid)
            if state is None:
                state = SessionState(sid=sid)
                self._states[sid] = state
            state.reset()
            return state


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

STYLE = """
*{box-sizing:border-box}body{font-family:Segoe UI,Arial,sans-serif;margin:0;
background:#f6f7fb;color:#101828}header{background:#111827;color:#fff;
padding:14px 28px;display:flex;gap:24px;align-items:center}
header a{color:#fff;text-decoration:none;margin-right:16px}
main{max-width:880px;margin:32px auto;padding:0 20px}
.card{background:#fff;border:1px solid #e4e7ec;border-radius:14px;
padding:20px;margin:14px 0;box-shadow:0 2px 10px rgba(16,24,40,.04)}
input,button,select{font-size:16px;padding:10px 12px;border-radius:9px;
border:1px solid #cfd4dc}button,a.btn{background:#2563eb;color:#fff;
border:none;cursor:pointer;text-decoration:none;display:inline-block;
padding:10px 16px;border-radius:9px}button:hover,a.btn:hover{background:#1d4ed8}
.muted{color:#667085}.price{color:#b42318;font-weight:700}
.row{display:flex;justify-content:space-between;align-items:center;gap:16px}
.pill{background:#eef2ff;color:#3538cd;border-radius:999px;padding:4px 10px;
font-size:13px}nav{margin-left:auto}
"""


def _page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{STYLE}</style></head><body>"
        "<header><strong>StepShop</strong>"
        "<a id='nav-home' href='/'>首页</a>"
        "<a id='nav-cart' href='/cart'>购物车</a>"
        "<nav><a href='/api/state'>状态</a></nav></header>"
        f"<main>{body}</main></body></html>"
    ).encode("utf-8")


def _product_card(p: Product) -> str:
    return (
        f"<div class='card'><div class='row'><div>"
        f"<a id='product-{p.pid}' href='/product/{p.pid}'>{p.name}</a>"
        f"<div class='muted'>{', '.join(p.keywords)}</div></div>"
        f"<div class='price'>¥{p.price}</div></div></div>"
    )


def render_home() -> bytes:
    cards = "".join(_product_card(p) for p in PRODUCTS.values())
    body = (
        "<div class='card'><h2>搜索商品</h2>"
        "<form action='/search' method='get'>"
        "<input id='q' name='q' placeholder='搜索商品' autocomplete='off'>"
        "<button id='search-btn' type='submit'>搜索</button></form>"
        "<p class='muted'>支持关键词：iphone / usb / 无线 / 蓝牙</p></div>"
        f"<h3>全部商品</h3>{cards}"
    )
    return _page("StepShop 首页", body)


def render_search(query: str) -> bytes:
    results = [p for p in PRODUCTS.values() if p.matches(query)]
    cards = "".join(_product_card(p) for p in results) or "<p>没有找到商品</p>"
    body = (
        "<div class='card'><form action='/search' method='get'>"
        f"<input id='q' name='q' value='{query}' placeholder='搜索商品'>"
        "<button id='search-btn' type='submit'>搜索</button></form>"
        f"<p>关键词：<strong id='query'>{query}</strong>，结果 {len(results)} 个</p>"
        f"</div>{cards}"
    )
    return _page("搜索结果", body)


def render_product(p: Product) -> bytes:
    body = (
        f"<div class='card'><h2 id='product-name'>{p.name}</h2>"
        f"<p class='price'>¥{p.price}</p>"
        "<form action='/add/{pid}' method='get'>"
        "<label>数量 <input id='qty' name='qty' type='number' value='1' min='1' max='9'></label>"
        "<button id='add-to-cart' type='submit'>加入购物车</button></form>"
        "<p class='muted'>关键词：" + ", ".join(p.keywords) + "</p></div>"
    ).replace("{pid}", p.pid)
    return _page(p.name, body)


def render_cart(state: SessionState) -> bytes:
    rows = []
    total = 0
    for pid, qty in state.cart.items():
        p = PRODUCTS.get(pid)
        if not p:
            continue
        total += p.price * qty
        rows.append(
            f"<div class='card row'><span id='cart-{pid}'>{p.name} × {qty}</span>"
            f"<span class='price'>¥{p.price * qty}</span></div>"
        )
    if not rows:
        rows.append("<p class='muted'>购物车是空的</p>")
    body = (
        "<h2>购物车</h2>"
        + "".join(rows)
        + f"<p>合计：<strong class='price'>¥{total}</strong></p>"
        + "<a id='checkout-btn' class='btn' href='/checkout'>去结算</a>"
    )
    return _page("购物车", body)


def render_checkout(state: SessionState) -> bytes:
    if not state.cart:
        body = "<div class='card'><h2>购物车为空</h2><p>请先添加商品。</p></div>"
        return _page("结算", body)
    body = (
        "<h2>结算</h2><div class='card'>"
        "<form action='/place-order' method='post'>"
        "<p><label>收货人 <input id='name' name='name' placeholder='收货人姓名'></label></p>"
        "<p><label>地址 <input id='address' name='address' placeholder='收货地址'></label></p>"
        "<button id='place-order' type='submit'>提交订单</button>"
        "</form></div>"
        "<script>"
        "const sync=()=>fetch('/api/form?name='+encodeURIComponent("
        "document.getElementById('name').value)+'&address='+"
        "encodeURIComponent(document.getElementById('address').value));"
        "document.getElementById('name').addEventListener('input',sync);"
        "document.getElementById('address').addEventListener('input',sync);"
        "</script>"
    )
    return _page("结算", body)


def render_order(order: Dict[str, object]) -> bytes:
    items = order.get("items", {})
    names = ", ".join(
        f"{PRODUCTS[pid].name}×{qty}" for pid, qty in items.items() if pid in PRODUCTS
    )
    body = (
        "<div class='card'><h2 id='order-title'>下单成功</h2>"
        f"<p>订单号：<span id='order-id'>{order.get('id')}</span></p>"
        f"<p id='order-items'>{names}</p></div>"
    )
    return _page("订单成功", body)


def render_error(message: str) -> bytes:
    return _page(
        "请求错误", f"<div class='card'><h2>请求错误</h2><p>{message}</p></div>"
    )


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server_version = "StepShop/1.0"

    @property
    def store(self) -> SessionStore:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        return

    # -- helpers ---------------------------------------------------------
    def _sid(self) -> str:
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k == "sid":
                    return v
        return ""

    def _send(
        self,
        body: bytes,
        status: int = 200,
        sid: Optional[str] = None,
        ctype: str = "text/html; charset=utf-8",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if sid:
            self.send_header("Set-Cookie", f"sid={sid}; Path=/; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, sid: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Set-Cookie", f"sid={sid}; Path=/; SameSite=Lax")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _state(self) -> SessionState:
        return self.store.get(self._sid())

    def _record(self, state: SessionState, path: str) -> None:
        state.visited.append(path)
        if len(state.visited) > 200:
            del state.visited[:-200]

    # -- GET -------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        state = self._state()
        sid = state.sid

        if path == "/api/state":
            self._send(
                json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8"),
                sid=sid,
                ctype="application/json; charset=utf-8",
            )
            return
        if path == "/api/reset":
            state.reset()
            self._send(
                b'{"ok": true}', sid=sid, ctype="application/json; charset=utf-8"
            )
            return
        if path == "/api/form":
            if "name" in qs:
                state.form["name"] = qs["name"][0]
            if "address" in qs:
                state.form["address"] = qs["address"][0]
            self._send(
                json.dumps(state.form, ensure_ascii=False).encode("utf-8"),
                sid=sid,
                ctype="application/json; charset=utf-8",
            )
            return
        if path == "/api/products":
            payload = [vars(p) for p in PRODUCTS.values()]
            self._send(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                sid=sid,
                ctype="application/json; charset=utf-8",
            )
            return

        self._record(state, self.path)

        if path == "/":
            body = render_home()
        elif path == "/search":
            state.query = qs.get("q", [""])[0]
            body = render_search(state.query)
        elif path.startswith("/product/"):
            pid = path.split("/", 2)[2]
            body = (
                render_product(PRODUCTS[pid])
                if pid in PRODUCTS
                else render_error("商品不存在")
            )
        elif path.startswith("/add/"):
            pid = path.split("/", 2)[2]
            try:
                qty = int(qs.get("qty", ["1"])[0])
            except ValueError:
                self._send(render_error("数量必须是整数"), 400, sid)
                return
            if pid not in PRODUCTS or not 1 <= qty <= 9:
                self._send(render_error("非法商品或数量"), 400, sid)
                return
            state.cart[pid] = min(9, state.cart.get(pid, 0) + qty)
            self._redirect("/cart", sid)
            return
        elif path == "/cart":
            body = render_cart(state)
        elif path == "/checkout":
            body = render_checkout(state)
        elif path.startswith("/order/"):
            if state.order and state.order.get("id") == path.split("/", 2)[2]:
                body = render_order(state.order)
            else:
                body = render_error("订单不存在")
        else:
            self._send(render_error("页面不存在"), 404, sid)
            return
        self._send(body, sid=sid)

    # -- POST ------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        state = self._state()
        sid = state.sid
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = {k: v[0] for k, v in parse_qs(raw).items()}

        if path == "/api/reset":
            state.reset()
            self._send(b'{"ok": true}', sid=sid, ctype="application/json")
            return
        if path == "/place-order":
            state.form = {
                "name": form.get("name", ""),
                "address": form.get("address", ""),
            }
            name = state.form["name"].strip()
            address = state.form["address"].strip()
            if not state.cart:
                self._send(render_error("购物车为空"), 400, sid)
                return
            if not name or not address:
                self._send(render_error("收货人和地址不能为空"), 400, sid)
                return
            order_id = uuid.uuid4().hex[:10]
            state.order = {"id": order_id, "items": dict(state.cart)}
            state.cart = {}
            self._redirect(f"/order/{order_id}", sid)
            return

        self._send(render_error("接口不存在"), 404, sid)


class LocalShopServer:
    """Background HTTP server with isolated sessions."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.store = SessionStore()  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self.host = host
        self.port = self._httpd.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> "LocalShopServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> "LocalShopServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
