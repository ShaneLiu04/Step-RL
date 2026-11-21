# [AR032] 设计

- Local 3 任务走真实 runtime（0 LLM）；
- 远程调用 AR029/AR030 adapters，记录 title/blocked/item_links；
- 空标题/无商品链接判失败；
- `ar032_demo_mp4.py` 用 AR028 GIF 帧与远程真实截图，经 ffmpeg 编码。
