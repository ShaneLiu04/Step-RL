# AR032 跨站评测状态报告（真实条件）

> 不伪造成功率。远程站点只读；样本/账号受限，未做 n≥30 与置信区间。

## 结果（2026-11-21）

| 站点 | 状态 | 证据 |
|------|------|------|
| Local | **3/3 成功**，0 LLM，steps 6/10/10 | `outputs/ar032/eval/ar032_results.json` |
| JD | 搜索页可打开，但 `item_links=0` → **失败** | `outputs/ar032/jd/20261121_184434_bb57d6/` |
| Taobao | 空标题/反爬 → **失败** | `outputs/ar032/taobao/20261121_184451_202212/` |
| Amazon | 搜索页真实加载（只读成功） | `outputs/ar032/amazon/20261121_184503_f11087/` |

## 结论

- Local adapter/runtime 闭环成立；
- 跨站“读出页面”部分成立（Amazon），但 JD/淘宝商品结果/后续链路被登录、反爬或 DOM
  差异阻断；不把“页面打开”冒充业务成功；
- 跨站 baseline/CI/MP4 多站成功演示需要账号、登录接管与更多样本，当前不标记 PASS；
- MP4：`docs/images/ar032_demo.mp4`（37KB，真实本地/远程截图帧）。
