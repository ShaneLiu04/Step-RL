"""Open a real Edge window and wait for manual JD login (AR029).

The script never asks for a password.  It waits for JD auth cookies
(pt_key/thor/wskey), saves storage_state locally, and exits.  No order/payment.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.adapters.jd import JDAdapter  # noqa: E402

AUTH_COOKIES = {"pt_key", "thor", "wskey"}


def default_cred() -> Path:
    import os

    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "StepRL" / "credentials" / "jd.json"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage-state", default=str(default_cred()))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    target = Path(args.storage_state)
    adapter = JDAdapter(headless=False, allow_submit=False)
    try:
        await adapter.open_session(manual_login=True)
        print(
            "已打开京东登录页。请在弹出的 Edge 窗口中完成登录/扫码/验证码。\n"
            "脚本检测到 pt_key/thor/wskey 后会自动保存并退出，无需终端按键。",
            flush=True,
        )
        deadline = asyncio.get_event_loop().time() + args.timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                cookies = await adapter._context.cookies()
            except Exception:
                cookies = []
            names = {str(cookie.get("name")) for cookie in cookies}
            if names & AUTH_COOKIES:
                await adapter.save_storage_state(str(target))
                shot = ROOT / "outputs" / "ar029" / "jd" / "login_success.png"
                shot.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shot.write_bytes(await adapter.page.screenshot())
                except Exception:
                    pass
                print(
                    f"LOGIN_SAVED {target} cookies={sorted(names & AUTH_COOKIES)} "
                    f"at={datetime.now().isoformat(timespec='seconds')}",
                    flush=True,
                )
                return 0
            await asyncio.sleep(2)
        print("LOGIN_TIMEOUT: 未检测到 JD 登录 Cookie", flush=True)
        return 2
    finally:
        await adapter.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
