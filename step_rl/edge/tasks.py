"""Task specifications for the real local shop.

SFT tasks only cover search/add (L1-L2).  RL tasks cover quantity, checkout
and multi-item flows (L3-L5).  Evaluation uses *held-out* products (p3/p4)
and combinations that never appear in SFT or RL training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    level: int
    goal: str
    search_query: str
    targets: Dict[str, int]
    require_checkout: bool = False
    start_path: str = "/"
    split: str = "train"

    def predicate_names(self) -> List[str]:
        names = ["search_done"]
        if self.level >= 2:
            names.append("product_viewed")
            names.append("cart_contains")
        if self.require_checkout:
            names.extend(
                [
                    "cart_viewed",
                    "checkout_viewed",
                    "name_filled",
                    "address_filled",
                    "order_placed",
                ]
            )
        return names

    def product_ids(self) -> List[str]:
        return list(self.targets.keys())


def _task(
    task_id: str,
    level: int,
    query: str,
    targets: Dict[str, int],
    checkout: bool,
    split: str,
) -> TaskSpec:
    action = "完成结算下单" if checkout else "加入购物车"
    items = "、".join(f"{pid}×{qty}" for pid, qty in targets.items())
    goal = f"搜索“{query}”，将商品 {items} {action}。"
    return TaskSpec(
        task_id=task_id,
        level=level,
        goal=goal,
        search_query=query,
        targets=targets,
        require_checkout=checkout,
        split=split,
    )


# --- SFT: only L1-L2, only p1/p2 -----------------------------------------
SFT_TASKS: List[TaskSpec] = [
    _task("sft_search_p1", 1, "iphone", {"p1": 1}, False, "sft"),
    _task("sft_search_p2", 1, "usb", {"p2": 1}, False, "sft"),
    _task("sft_add_p1", 2, "iphone", {"p1": 1}, False, "sft"),
    _task("sft_add_p2", 2, "usb", {"p2": 1}, False, "sft"),
    _task("sft_add_p1x2", 2, "iphone", {"p1": 2}, False, "sft"),
    _task("sft_add_p2x2", 2, "usb", {"p2": 2}, False, "sft"),
    _task("sft_search_p1_alt", 1, "手机", {"p1": 1}, False, "sft"),
    _task("sft_search_p2_alt", 1, "cable", {"p2": 1}, False, "sft"),
    _task("sft_add_p1_alt", 2, "apple", {"p1": 1}, False, "sft"),
    _task("sft_add_p2_alt", 2, "充电", {"p2": 1}, False, "sft"),
]

# --- RL: L3-L5, only p1/p2, flows unseen in SFT ---------------------------
TRAIN_RL_TASKS: List[TaskSpec] = [
    _task("rl_qty_p1", 3, "iphone", {"p1": 2}, False, "train"),
    _task("rl_qty_p2", 3, "usb", {"p2": 2}, False, "train"),
    _task("rl_checkout_p1", 4, "iphone", {"p1": 1}, True, "train"),
    _task("rl_checkout_p2", 4, "usb", {"p2": 2}, True, "train"),
    TaskSpec(
        task_id="rl_multi_p1p2",
        level=5,
        goal="搜索“iphone”并加入 iPhone 15；再搜索“usb”并加入 USB-C 数据线×2；最后完成结算下单。",
        search_query="iphone",
        targets={"p1": 1, "p2": 2},
        require_checkout=True,
        split="train",
    ),
]

# --- Evaluation: held-out products p3/p4 and unseen combos ----------------
EVAL_TASKS: List[TaskSpec] = [
    _task("ev_search_p3", 1, "无线", {"p3": 1}, False, "eval"),
    _task("ev_search_p4", 1, "蓝牙", {"p4": 1}, False, "eval"),
    _task("ev_add_p4", 2, "蓝牙", {"p4": 1}, False, "eval"),
    _task("ev_add_p3", 2, "无线", {"p3": 1}, False, "eval"),
    _task("ev_qty_p3", 3, "无线", {"p3": 2}, False, "eval"),
    _task("ev_qty_p4", 3, "蓝牙", {"p4": 2}, False, "eval"),
    _task("ev_checkout_p4", 4, "蓝牙", {"p4": 1}, True, "eval"),
    _task("ev_checkout_p3", 4, "无线", {"p3": 2}, True, "eval"),
    TaskSpec(
        task_id="ev_multi_p3p4",
        level=5,
        goal="搜索“无线”并加入无线充电器；再搜索“蓝牙”并加入蓝牙降噪耳机×2；最后完成结算下单。",
        search_query="无线",
        targets={"p3": 1, "p4": 2},
        require_checkout=True,
        split="eval",
    ),
]


ALL_TASKS: List[TaskSpec] = SFT_TASKS + TRAIN_RL_TASKS + EVAL_TASKS
TASK_BY_ID = {t.task_id: t for t in ALL_TASKS}
