# P19 — 1–2 minute demo walkthrough

**视频状态：NOT RECORDED。** P19 实现阶段已生成并检查三张本地应用截图，本次文档同步
确认文件仍存在，没有新的实际视频文件或录制记录。用户报告发布完成不会改变素材来源：
图片仍为 **Local fixture demonstration**。下面约 100 秒流程是可选录制脚本，
不是已完成的公网视频验收，也不阻塞 P19 代码实现或发布完成状态。

## 安全、可重复的本地演示

在项目 `frontend` 目录运行以下命令：它启动本机 Vite，用隔离 fixture 驱动真实 React UI，
生成三张精选 JPG 后结束。成功是两套屏幕下相应用例通过；失败先看测试断言，不能改分数、
跳过账号切换或改真实环境文件来让它通过。需要已安装本项目 Playwright Chromium。

```bash
RUN_UI_E2E=0 CAPTURE_P19_SCREENSHOTS=1 npm run test:e2e -- --grep 'P19 forced-finalized'
```

若想自己观看，给上面命令加 `--headed --workers=1 --project=desktop-chromium`。
用 Playwright Inspector 的 pause/step（`PWDEBUG=1`）放慢本地 fixture 过程，再使用系统
屏幕录制；**不要录下 Inspector 网络、Console、登录态或其他桌面窗口**。
标题始终保留 `Local fixture demonstration · Not cloud acceptance · Test / Sandbox / Demo`。
普通测试关闭真实 flow，单独的账号切换 fixture 不生成截图/trace/video。

## 精选截图（已生成、已逐张打开检查）

| 图片 | 展示内容 | 检查要点 |
| --- | --- | --- |
| [p19-01.jpg](images/p19-01.jpg) | 草稿、日期/预算/偏好与显式确认 | 完整本地 fixture，没有账号资料 |
| [p19-02.jpg](images/p19-02.jpg) | 五路搜索、route 不可用、审核修改中 | 这是中间态，Improving 仅此时合理 |
| [p19-03.jpg](images/p19-03.jpg) | 62.5 分 forced-finalized 草稿与来源/费用限制 | Workflow ended；不是通过；没有活动 spinner/Improving |

图片来自运行中的应用，不是绘图。三张都标明 fixture，无邮箱、真实身份、token、Cookie
或可用认证状态；Connected 是被 fixture 模拟的健康指示，不是 Auth0 验收。
来源标签是示例响应中的 Duffel Test / LiteAPI Sandbox / Demo，不代表调用了这些 API。
Route 的 Demo 标签表示 provider 来源，上方同时明确 unavailable。全页布局已查看，
无重要文字裁切、遮挡；第三张较长，应打开原图阅读，不以缩略图证明细节。

## 约 100 秒讲解脚本

| 时间 | 屏幕动作 | 旁白 |
| --- | --- | --- |
| 0–12s | 应用标题和 fixture 标注 | 这是有状态旅行规划工作流，不是订票平台；当前是本地示例 |
| 12–30s | 输入目的地，补齐出发地、未来日期、人数、预算/币种和偏好 | 系统先澄清需求，不会看到一句话就直接替你执行 |
| 30–40s | 看草稿，点击 Confirm & Build My Trip | 只有显式确认后的需求进入规划 |
| 40–60s | 五路搜索和审核卡 | LangGraph 并行找候选；route 没有可靠范围，明确不可用，而不是编一个时长 |
| 60–80s | 最终质量卡、来源、价格 | 这个示例到达最多轮次，62.5 分保留为待检查草稿；结束不等于通过；返程/到店费用不包含 |
| 80–100s | 刷新，查看同一结果 | 读取已有计划和审核摘要，不重新调用模型；Test/Sandbox/Demo 不是实时可预订库存 |

日期示例为 2027-10-12 至 2027-10-16，1 人，3000 USD；录制真实流前重新确认日期仍在未来。
如果酒店需要 guest nationality，必须由用户明确提供，不能从出发地/语言推断。
Fixture 自动测试有意返回固定结果；真实模型的分数与审核轮次不保证相同。

真实公网录制须先获授权、确认 P19 revision 和调用预算、完成登录与隐私检查。
最多运行获准的一次规划，不循环调用直到高分；遇到 forced_finalize 就如实展示。
不要为录制清空限流、开放私有服务、隐藏低分或打开 silent fallback。

## 可以讲清楚的三个工程选择

1. **不只是 Qwen wrapper**：应用负责候选事实、严格结构、grounding、graph 状态与用户边界；
   模型负责在受限候选里做决策，不能自行造价格和库存。
2. **供应商权限是现实约束**：历史 Duffel Stays 没有账户访问权，已有 LiteAPI Sandbox
   酒店适配保持搜索接口边界。该历史结果不是本轮又一次真实调用，仍没有预订功能。
3. **资源问题用证据定位**：P18 曾验证本地 1 GiB fresh-index OOM、2 GiB 本地通过；
   采用有界 bootstrap 与模型生命周期处理。不能说已证明 Railway 的 OOM 原因或 1 GiB 可运行。
