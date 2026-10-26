# 文档导航

当前代码已包含评分闭环、实时通知、导出、部署和备份恢复工具。完整容量/故障演练、实机验收和 CloudBase 正式域名业务验收仍有待办，不能以历史测试通过替代上线验收。

## 开发与设计

| 文档 | 用途 |
| --- | --- |
| [项目 README](../README.md) | 本地安装、启动与开发命令 |
| [产品需求与架构设计](在线打分系统-产品需求与架构设计.md) | 产品规则、架构和验收标准 |
| [API 文档](api.md) | 接口、认证、状态与错误约定 |
| [提交计划](commit-plan.md) | 开发批次和历史进度 |
| [前端计划](frontend-plan.md) | 页面分工与前端实现约定 |
| [政工案例评审活动更新方案](political-case-review-update-plan.md) | 四维评分模板、新活动类型和专用大屏的改造方案（待实施） |
| [政工案例评分简化方案](political-case-review-simplified-plan.md) | 复用多维度评分，增加可选大屏模板及逐项累计预览（待实施） |
| [Review 索引](review/README.md) | 各批次实现范围和验证证据 |

## 部署与操作

| 文档 | 用途 |
| --- | --- |
| [CloudBase 部署](cloudbase-deployment.md) | 当前云环境、容器、静态托管及同源路由 |
| [CloudBase 连接检查](cloudbase-connection-check.md) | 最近一次实测结果、检查范围及剩余阻塞 |
| [Compose 生产部署](deployment.md) | 自建服务器的另一套部署方案 |
| [备份与恢复](backup-recovery.md) | 备份、异库恢复和容量检查 |
| [主持人手册](host-guide.md) | 活动前准备、评分操作及常见情况 |

## 验收

| 文档 | 用途 |
| --- | --- |
| [上线检查单](go-live-checklist.md) | 目标环境正式上线前逐项确认 |
| [评分流程验收证据](acceptance-21.md) | AT 自动化覆盖及证据边界 |
| [实机验收记录](device-acceptance.md) | 手机、微信和投影设备的待测项 |

## UI 参考

- [大屏玻璃风格原型](ui/dashboard-glass.html)
- [加入活动原型](ui/join-activity.html)

## 维护约定

通用说明保留在本目录；批次 review 集中于 `review/`，UI 原型集中于 `ui/`。更新文档时同步维护相对链接和本索引。

Review 中的“当前”“待提交”和测试数量均描述该批次记录时的状态，不代表今天的 Git 状态或生产环境。部署事实按日期记录；检查结果需注明实际检查范围，未测项目继续保留待办。
