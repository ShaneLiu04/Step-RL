"""AR029 JD dry-run runner (real Edge, manual login, no submit/payment).

Usage examples:
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --manual-login
  python scripts/ar029_jd_dryrun.py --query "USB-C" --product https://item.jd.com/...
      --storage-state "$env:LOCALAPPDATA\\StepRL\\credentials\\jd.json" --to-checkout

AR029 never clicks 提交订单/支付.  It stops at the checkout page.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.adapters.evidence import EvidenceWriter  # noqa: E402
from step_rl.edge.adapters.jd import JDAdapter, jd_search_url  # noqa: E402


def default_storage_state() -> str:
    import os

    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return str(Path(base) / "StepRL" / "credentials" / "jd.json")


async def run(args) -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    writer = EvidenceWriter(ROOT / "outputs" / "ar029", run_id, "jd")
    adapter = JDAdapter(
        evidence=writer,
        headless=args.headless,
        min_action_interval=args.min_interval,
        max_pages=args.max_pages,
        max_amount=args.max_amount,
        allow_submit=False,
    )
    result = {
        "run_id": run_id,
        "site": "jd",
        "dry_run": True,
        "query": args.query,
        "search_url": jd_search_url(args.query),
        "steps": [],
        "manual_login": bool(args.manual_login),
        "evidence_dir": str(writer.root),
    }
    try:
        await adapter.open_session(
            storage_state=args.storage_state,
            manual_login=args.manual_login,
        )
        if args.manual_login:
            print(
                "请在真实 Edge 中完成 JD 登录/验证码；完成后回到终端按 Enter 继续...",
                flush=True,
            )
            input()
            if args.save_storage_state:
                await adapter.save_storage_state(args.storage_state)
                result["storage_state_saved"] = args.storage_state
        obs = await adapter.search(args.query)
        result["search_title"] = obs.title
        result["search_page_type"] = obs.page_type
        result["steps"].append({"step": "search", "url": obs.url})
        await adapter.capture("search")
        writer.step({"step": "search", "url": obs.url, "title": obs.title})

        if args.product:
            obs = await adapter.open_product(args.product)
            result["product_title"] = obs.title
            result["product_amount"] = obs.signals.get("amount")
            result["steps"].append({"step": "product", "url": obs.url})
            await adapter.capture("product")
            writer.step({"step": "product", "url": obs.url, "amount": obs.signals.get("amount")})

        if args.add_to_cart:
            obs = await adapter.add_to_cart(args.quantity)
            result["cart_after_add"] = await adapter.read_cart()
            result["steps"].append({"step": "cart", "url": obs.url})
            writer.step({"step": "cart", "url": obs.url, "text": adapter.current_text[:500]})

        if args.cart_quantity is not None:
            obs = await adapter.set_cart_quantity(args.cart_quantity)
            result["cart_after_quantity"] = await adapter.read_cart()
            result["steps"].append({"step": "cart_quantity", "url": obs.url})
            await adapter.capture("cart_quantity")
            writer.step({"step": "cart_quantity", "quantity": args.cart_quantity, "url": obs.url})

        if args.remove_cart:
            obs = await adapter.remove_from_cart()
            result["cart_after_remove"] = await adapter.read_cart()
            result["steps"].append({"step": "cart_remove", "url": obs.url})
            await adapter.capture("cart_remove")
            writer.step({"step": "cart_remove", "url": obs.url})

        if args.orders:
            result["orders"] = await adapter.read_orders()
            result["steps"].append({"step": "orders", "url": result["orders"].get("url")})
            writer.step({"step": "orders", "orders": result["orders"]})

        if args.to_checkout:
            checkout = await adapter.open_checkout()
            verification = await adapter.verify_checkout_dryrun()
            result["checkout"] = checkout
            result["verification"] = {
                "success": verification.success,
                "progress": verification.progress,
                "predicates": verification.predicates,
                "evidence": verification.evidence,
            }
            result["steps"].append({"step": "checkout_dry_run", "url": checkout.get("url")})
            writer.step(
                {
                    "step": "checkout_dry_run",
                    "checkout": checkout,
                    "verification": verification.__dict__,
                }
            )
        result["ok"] = True
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        writer.step({"step": "error", "error": result["error"]})
    finally:
        await adapter.close()
        writer.summary(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="AR029 JD dry-run (no submit/payment)")
    parser.add_argument("--query", default="无线充电器")
    parser.add_argument("--product", default="")
    parser.add_argument("--storage-state", default=default_storage_state())
    parser.add_argument("--manual-login", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--add-to-cart", action="store_true")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--cart-quantity", type=int, default=None)
    parser.add_argument("--remove-cart", action="store_true")
    parser.add_argument("--orders", action="store_true")
    parser.add_argument("--to-checkout", action="store_true")
    parser.add_argument("--save-storage-state", action="store_true")
    parser.add_argument("--min-interval", type=float, default=5.0)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-amount", type=float, default=200.0)
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
