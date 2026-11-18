# 终端经营数据驾驶舱

AI Coding 实战训练项目。以虚拟终端经营数据为基础，展示收入、销量和完成进度，并支持省份一级详情、模拟诊断与告警。

## 主要功能

- 展示省份收入、销量、完成率及同比；使用空间热力图、月度折线图和渠道占比环形图。
- 点击省份或省份列表进入一级详情，查看品类、渠道和当前省份的模拟 AI 诊断。
- 后端通过 WebSocket 推送模拟数据更新、告警和重置；支持预设问题的规则模拟回答。
- 虚拟数据可用固定种子重新生成；不连接企业系统或真实经营数据。

技术：React 19、JavaScript、Vite 6、ECharts 5、Python、FastAPI、SQLite 和 WebSocket。

## 安装与运行

Windows 环境需要 Python 3.10 以上和 Node.js（推荐 22），并确保命令行能找到 `python` 和 `npm`。

1. 克隆或下载本仓库并完整解压。
2. 双击 `install.cmd`，联网安装依赖、生成虚拟数据库、下载学习交流用地图并构建前端。
3. 双击 `start.cmd`，浏览器打开 `http://127.0.0.1:8765/`。
4. 演示结束双击 `stop.cmd`。端口被占用时不会停止其他进程。

也可手动执行：

```powershell
python -m pip install -r requirements.txt
npm ci
python scripts/generate_seed.py --output data/seed.sqlite
python scripts/prepare_map.py
npm run build
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

数据库生成脚本不会覆盖现有文件；已有 `data/seed.sqlite` 时跳过生成命令。`install.cmd` 在缺失时才生成。安装过程需要网络；之后运行使用本地资源。

## 演示说明

- 逻辑演示日期固定为 2026-06-18，默认业务数据为 2026-06-17。日期范围为 2026-01-01 至 2026-06-17，2025 年同期用于同比。
- 演示用虚拟数据默认每 15 秒修订一次，模拟 WebSocket 更新。点击“演示触发异常”可生成虚拟告警，点击“重置演示”恢复初始数据。
- AI 诊断和两个预设问题由规则模板生成，**没有接入大模型**。诊断和告警不能用于真实经营决策。
- 热力图将省级虚拟收入映射到省会近似锚点，不代表真实网点分布。

## 地图来源与使用范围

本仓库不包含第三方地图数据。首次安装时脚本从阿里云 DataV.GeoAtlas 下载所需数据。DataV 的[官方说明](https://help.aliyun.com/zh/datav/datav-7-0/user-guide/datav-geoatlas-widgets/)称数据来自高德开放平台，**仅供学习交流**；公开展示、商用及地图审图要求需另行核实。本项目用于课程练习，不声明地图已取得公开出版或生产使用授权。

## 检查

```powershell
python -m unittest backend.test_app -v
```

后端测试覆盖虚拟数据汇总、WebSocket 推送、告警和重置。当前已完成前端构建与后端接口测试；浏览器可视布局和点击流程尚未完成自动化验收。详见 `AI复盘.md`。
