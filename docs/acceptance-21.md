# 工作 21 验收证据索引

基线：产品需求与架构设计 V1.1 的 AT-01～26、29。执行结果见 [Review 21](review-21.md)。

证据层次：`backend/tests/` 中带 `_mysql` 的测试使用真实 MySQL 和应用 HTTP 处理链，实时测试另外使用 Redis，其中多进程测试启动两个 Uvicorn 进程。新增 `test_workflow_mysql.py` 使用 TestClient 驱动 API，未启动浏览器。`frontend/src/` 测试使用 jsdom/模拟 API 或 WebSocket，不等同于浏览器与真机测试。下表是功能覆盖索引，不代表正式部署容量和所有终端均已验收。

后端文件以下省略 `backend/tests/`，前端文件省略 `frontend/src/`。同一单元格列出的测试共同构成该项证据。

| 编号 | 自动化证据 | 范围及尚需外部验证 |
| --- | --- | --- |
| AT-01 | `test_workflow_mysql.py::test_five_judges_three_entries_create_to_archive`（mean、trimmed_mean） | 主办方真实登录、创建、发布、5 个独立评委会话、3 个对象、收评/补评/公布、三类 CSV、结束归档；API 闭环，未声称 UI 全流程自动化 |
| AT-02 | `test_judge_sessions_mysql.py::test_preview_confirmation_cookie_me_and_logout`；`judge/pages.test.tsx` joining and identity | 手输码与邀请路径、身份确认、未验证拒绝；摄像头扫码及微信跳转见真机记录 |
| AT-03 | `test_judge_sessions_mysql.py::test_second_device_blocked_same_device_does_not_extend_and_identity_switch` | 独立 Cookie 模拟第二设备，验证单有效会话 |
| AT-04 | 新增闭环逐对象检查评委任务 OPEN、大屏任务 ID 和 0/5；`judge/pages.test.tsx` 对象切换测试 | API 三角色状态一致；手机实际推送展示需真机 |
| AT-05 | `test_scoring.py::test_at05_weighted_personal_total`；`test_ballots_mysql.py::test_multidimensional_score_and_canonical_order`；`judge/pages.test.tsx` previews 87.00 | 90、8、18 → 87.00；小数原始输入和后端核算 |
| AT-06 | 新增闭环重复 key；`test_ballots_mysql.py::test_response_lost_after_commit_recovers_original_receipt`；`judge/pages.test.tsx` double clicked / timeout | 同 key 原回执、人数不重复；丢响应注入与前端重试 |
| AT-07 | 新增闭环改分 1→2→3 和旧 revision 冲突；`test_ballots_mysql.py::test_concurrent_submissions` | 真实并发覆盖相同 key、不同 key 和修订冲突；历史保留 |
| AT-08 | `test_ballots_mysql.py::test_receipt_survives_app_restart_and_is_private`；`judge/pages.test.tsx` refresh；`lib/realtime.test.ts` foreground | 进程恢复、页面刷新和前台恢复；OS 杀后台需真机 |
| AT-09 | `test_rounds_mysql.py::test_clock_pause_resume_and_versions`；`test_ballots_mysql.py::test_clock_checked_after_waiting_for_task_lock`；`test_worker_mysql.py::test_deadline_excludes_pause_unlimited_and_preserves_cutoff` | 注入服务端时钟验证截止，不依赖睡眠碰边界 |
| AT-10 | `test_results_mysql.py::test_close_races_submit_and_original_receipt` | 真实收评/提交竞争，冻结结果与提交是否成功一致 |
| AT-11 | 新增 trimmed_mean 闭环首对象；`test_scoring.py::test_at11_trimmed_mean_keeps_raw_ballots_and_marks_two_exclusions` | 80、85、90、95、100 → 90.00；5 份原始记录、2 个剔除标记 |
| AT-12 | 新增 trimmed_mean 闭环第二对象；`test_results_mysql.py::test_no_result_pause_close_and_active_reopen` | 4/5 可收评不可公布，补评后公布；无结果终态另测 |
| AT-13 | 新增 mean 闭环 4/5 收评；`test_results_mysql.py::test_five_judges_threshold_and_recomputation` | K=4，原因必填，按实交 4 份平均并可公布；API 的 valid_count/expected_count |
| AT-14 | 新增闭环逐次公布前隔离；`test_snapshots_mysql.py::test_private_scores_and_role_versions`；`test_realtime_mysql.py::test_roles_versions_and_multiple_api_instances` | 大屏无原始分/回执，未公布不进入公共结果，实时角色隔离 |
| AT-15 | 新增闭环三类 CSV 与冻结快照 ID/数值/规则版本；`test_exports_mysql.py`；[Review 20b](review-20b.md) | 本次 API CSV 检查；既有 Chrome 六类下载实测记录单独引用 |
| AT-16 | 新增闭环 1、2、2；`test_snapshots_mysql.py::test_tied_rankings_only_published_and_limit`；`test_scoring.py::test_at16_published_scores_competition_rank_and_display_order` | 四对象例子 1、2、2、4，且只包含已公布 |
| AT-17 | 新增闭环每个对象公布后拒绝改分/重开 | 归档后历史快照不变，已成功请求仍可查原回执 |
| AT-18 | `test_realtime_mysql.py::test_two_os_api_processes_receive_duplicates_without_cross_event` | 真实两个 API 进程、活动隔离；正式部署拓扑和容量留 23 |
| AT-19 | `test_realtime_mysql.py::test_crash_recovery_duplicate_delivery_and_concurrent_claims`；`lib/realtime.test.ts` lost final notification / repeated connection failures | Redis 发布失败注入、轮询/版本校对分别验证；物理断网演练留真机/23 |
| AT-20 | `test_realtime_mysql.py::test_crash_recovery_duplicate_delivery_and_concurrent_claims`；`test_ballots_mysql.py::test_receipt_survives_app_restart_and_is_private` | 租约过期重领模拟崩溃窗口、重建 app 后原回执；不是生产 kill -9 演练 |
| AT-21 | 新增闭环新对象开始后拒绝旧任务提交；`judge/pages.test.tsx` old-round / isolates drafts | 不将旧请求转写新对象，断线恢复不自动补交草稿 |
| AT-22 | 新增闭环撤销大屏；`test_judge_sessions_mysql.py::test_reset_rejects_current_duplicate_and_invalidates_old_code_sessions_confirmations`；`test_realtime_mysql.py::test_revocation_closes_connected_and_outstanding_tickets` | HTTP、已连接实时流、未用票据失效，历史保留 |
| AT-23 | 新增闭环其他主办方 404；`test_events_mysql.py::test_owner_isolation_every_route_and_csrf`；`test_realtime_mysql.py::test_tickets_origin_csrf_event_binding_replay_and_expiry` | HTTP 与实时票据越权拒绝 |
| AT-24 | 新增闭环检查 UNFINISHED_ROUNDS 和待处理 ID；`admin/control/control.test.tsx` | 完成前不得结束，页面错误处理另由组件测试覆盖 |
| AT-25 | `test_credentials_mysql.py::test_manual_auto_metadata_no_plaintext_or_hash_leaks`、`test_uniqueness_permissions_states_and_validation`、`test_concurrent_duplicate_and_database_constraint`；`test_judge_sessions_mysql.py` | 自动/手动、非法/重复、规范化、只当次明文及兑换 |
| AT-26 | `test_judge_sessions_mysql.py` reset 测试；`test_ballots_mysql.py::test_cross_event_rejected_and_copy_has_no_ballots`；`test_publication_mysql.py::test_copy_only_config_and_roster_with_fresh_ids` | 重置撤销与历史归属、副本名单/规则但无评分/凭证 |
| AT-29 | 新增 `test_workflow_mysql.py::test_two_closed_entries_concurrently_reopen_only_one`；`test_rounds_mysql.py::test_concurrent_control_only_one_wins`、`test_database_constraint_blocks_open_plus_paused` | 两个独立控制台同时重开不同 CLOSED 对象仅一个成功；活动锁/唯一索引限制单活跃任务 |

新增 `test_concurrent_five_judges_failed_commit_and_retry` 还将 outbox 写入失败、回滚可见性、五客户端并发提交、收评后原 key 重试串联验证，防止逐模块测试遗漏组合问题。

AT-27/30 的连接预算、限流与回源合并已有单项测试，但正式容量结论归工作 23；AT-28 的备份恢复与存储告警归工作 24。本批不将这些运维项标记完成。
