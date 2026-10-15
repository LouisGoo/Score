# 备份、异库恢复与保留策略（24）

本流程面向维护者。CSV 仅用于查阅，不能替代数据库备份。工具只读取显式的 `SCORE_BACKUP_DATABASE_URL` / `SCORE_RESTORE_DATABASE_URL`，不会自动读取项目 `.env` 的生产数据库地址。没有定时任务、自动删表或自动清理。

## 安装与保存位置

在受保护的 Linux 运维主机使用已安装项目依赖的 Python 环境，并安装 **MySQL 8.0 的 mysqldump/mysql 客户端**（不是 MariaDB 同名工具）。22 的应用镜像不自带这些客户端；以下示例从宿主机项目根目录运行 `.venv/bin/python`。客户端不在 PATH 时，分别加 `--mysqldump /路径/mysqldump` 和 `--mysql /路径/mysql`。

备份输出目录事先创建并设为 700；备份和清单为 600。建议放在项目目录之外，例如挂载的加密备份盘，并复制到独立于数据库及应用服务器的受控位置。不要放入公开下载目录或 Git。gzip 只是压缩，不是加密；操作系统管理员仍可读取文件和进程环境。

凭证从受保护的配置或密码管理器注入环境变量；不要把真实 URL 粘贴进聊天或写到脚本/命令历史。密码特殊字符须 URL 编码。TLS URL 参数支持 `ssl_ca`、`ssl_cert`、`ssl_key`、`ssl_verify_cert`、`ssl_verify_identity`；远程连接使用 CA 和服务器身份校验。CA 路径需在运维主机实际可读，不能直接沿用容器的 /certs 路径。其他 URL 参数会被客户端包装器拒绝，不会悄悄忽略。

## 频率、权限与恢复点

建议每天一次，正式活动开始前与结束后额外备份。先由负责人确定执行时间、保管人、保留份数和异地副本位置，再配置外部调度；本批不创建计划任务。每日备份意味着最坏可能丢失最近一次备份之后的数据，不承诺时间点恢复；需要更小恢复点时再确认 binlog 和托管平台能力。

源账号需能读取项目表和 information_schema 元数据；按 MySQL 版本、GTID 设置核实 mysqldump 所需权限。目标账号只应获准操作新建的恢复库，不使用能任意修改生产库的账号。免费数据库的权限、语句配额及空间必须先确认；备份、核对也消耗查询额度。

备份涵盖源库所有 `score_` 前缀 InnoDB 基表，包括迁移版本、账号/会话、规则快照、原始分、所有版本、幂等回执、审计、结果、大屏授权和 outbox。不会备份同库其他前缀的旧系统表。出现项目视图、非 InnoDB 表或自定义触发器时拒绝备份，需另定方案。项目不得把业务表改成其他前缀后继续声称工具全量覆盖。

## 执行备份

1. 确认连接目标正确、备份目录有足够空间，并暂停数据库迁移及任何 DDL。
2. 配置 `SCORE_BACKUP_DATABASE_URL` 后运行（替换文件名，禁止复用已有文件）：

```sh
.venv/bin/python -m score_api.ops backup /安全目录/score-20261015-220000.sql.gz
```

成功生成压缩 SQL 与同名 `.json` 清单，输出 `backup_complete`、表数和 SHA-256。mysqldump 使用单事务一致性快照，正常业务写入可以继续；备份期间不得 ALTER/CREATE/DROP/RENAME/TRUNCATE。命令失败返回 1，不将部分文件视为成功备份。

连接密码放进短时 600 权限客户端配置文件，不出现在客户端命令参数中；退出后清除。客户端原始 stderr 不输出，防止 URL、SQL 或凭证泄露。失败时依次检查客户端版本、目录权限、数据库连通性/TLS、账号权限和配额；需要详细诊断时仅在受控终端处理，禁止将原始输出直接上传。

保管 SQL、清单、所用代码版本/镜像标签和迁移版本。HMAC 密钥、环境配置、站点证书私钥分别安全备份，**数据库备份不包含这些配置文件**。丢失或更换原有 HMAC 密钥会影响既有身份码；不能用随机新密钥冒充恢复完成。

## 异库恢复演练

恢复只接受名称以 `_restore` 结尾的空数据库，并要求 `--confirm-target` 精确重复名称。目标库必须已由维护者创建，推荐在另一个 MySQL 实例；不能和清单中的源数据库同名。工具不创建/删除数据库、不执行覆盖、不自动切换应用。

仅恢复自己生成并安全保管的可信备份。清单 SHA-256 用于发现损坏，不提供真实性签名；SQL 备份本身可以执行 SQL，不可恢复第三方提供的未知文件。恢复账号限制在目标库，避免跨库影响。

需要逐字核对源和目标时，先在维护窗口停止所有 API、worker、管理员脚本及其他写入者（页面“暂停评分”不能阻止所有写入）。然后：

```sh
# SCORE_BACKUP_DATABASE_URL 为源库；SCORE_RESTORE_DATABASE_URL 为新建空库。
umask 077
.venv/bin/python -m score_api.ops fingerprint > /安全目录/source-fingerprint.json
.venv/bin/python -m score_api.ops backup /安全目录/drill.sql.gz
.venv/bin/python -m score_api.ops restore /安全目录/drill.sql.gz --confirm-target score_drill_restore
.venv/bin/python -m score_api.ops fingerprint --target > /安全目录/restored-fingerprint.json
cmp /安全目录/source-fingerprint.json /安全目录/restored-fingerprint.json
```

恢复先验证压缩包 SHA-256、gzip 完整性及空库条件，再导入并检查表集合。SQL DDL 不能整体回滚：导入失败可能留下部分数据，停止使用该目标，由维护者检查后新建另一个空库重试；不要重复向部分恢复库导入。

fingerprint 在一致性读事务中按主键顺序逐行计算哈希，输出每表行数及摘要，不输出业务行。大库核对需要时间、流量和语句额度。在线业务继续变化时不能用“当前源库摘要不同”认定旧备份损坏；正式逐表对照必须按上面的停写顺序完成。

恢复演练至少确认：

- 所有项目表行数/摘要一致，规则、原始分、改分版本、幂等回执、审计、outbox 和结果均在。
- 用与备份匹配的代码、原有 HMAC 密钥启动隔离 API，ready 返回 200。先不要运行 worker、不要接入正式 Redis/公网域名。
- 核对已公布成绩与导出；抽取原始分和冻结规则复算，验证去极值/权重/缺交及舍入。
- 原有有效会话在测试环境重放同一幂等 key 和原请求，应得到相同回执。不要在正式活动中用新 key“验证”旧提交。
- 记录备份时刻、恢复时长、表数、摘要比较结果、复算与回执结果、操作者和异常；只有恢复验证成功才算有效备份。

## 真正故障后的切换

1. 停止对故障源库的所有写入，保存故障现场。选定最近完整备份，向负责人说明恢复点之后可能丢失的数据。
2. 按上述流程恢复到独立空库，验证数据与代码版本；不要直接把备份导回原库。
3. 恢复配置与密钥，决定是否需要显式撤销恢复出的旧会话/大屏授权。旧会话、凭证重置和撤销状态也回到备份时刻，不能假定仍与故障前一致。
4. 检查备份中的 OPEN 任务和到期时间。worker 启动后会关闭已到期任务；先核对再启动 worker。恢复的未投递 outbox 会重投，属于至少一次投递。
5. 评估旧 Redis 票据残留，使用隔离的新 Redis 或等待旧票据过期，避免新旧应用交叉连接。确认只有一套 API/worker 写入目标库后，再修改应用连接并恢复入口。
6. 检查真实域名登录、评委回执、大屏、导出与 ready。恢复后有新写入就不能直接切回旧库；若要回退，必须先停写并核对差异。

## 容量预警

```sh
.venv/bin/python -m score_api.ops storage
.venv/bin/python -m score_api.ops storage --warning-mb 350 --critical-mb 425
```

默认按十进制 MB（1MB=1,000,000 字节）计算：低于 350MB 返回 0；达到 350MB 返回 warning/10；达到 425MB 返回 critical/20；连接或参数失败返回 failed/1。阈值必须满足 0 < warning < critical，可按真实额度调整。

统计当前库 **全部表** 的 DATA_LENGTH + INDEX_LENGTH，包含同库旧系统表，避免低估共享配额。这是 information_schema 估计值，不能替代提供方控制台计费口径，空库零值也不表示连接失败。没有定时告警推送：维护者活动前后手动检查，或自行接入已有调度。

350MB：核对增长来源、备份副本和可用空间；425MB：安排扩容或经确认的历史处理，预留活动与迁移空间。归档不会删除数据、不会释放空间，DELETE 后物理文件和提供方用量也未必立即下降。不为腾空间直接 OPTIMIZE 全库。

## outbox、会话与正式数据的保留

下表是维护策略建议，**不会自动执行**。清理前先确认保留期限、备份和恢复演练，活动期间不清理；每批最多 500 行，先 SELECT COUNT，记录实际影响行数，分批提交，出现锁等待即停止。

| 数据 | 建议可清理条件 |
| --- | --- |
| score_outbox | delivered_at 非空且早于当前 UTC 7 天，并且 claim_token 为空；未投递事件及仍持有租约的事件不删 |
| score_admin_sessions / score_judge_sessions | expires_at 早于当前 UTC 7 天；仅撤销但尚未过期的会话先保留 |
| score_judge_confirmations | expires_at 早于当前 UTC 7 天；无论是否消费，未过期的都保留 |
| score_login_buckets | expires_at 早于当前 UTC 1 天 |
| 评分、各版本、结果、规则快照、幂等记录、全部审计、人员/凭证 | 不提供自动清理；180 天只是待负责人确认的建议，不是到期删除规则 |

例如审核 outbox 清理候选（只读）：

```sql
SELECT COUNT(*) FROM score_outbox
WHERE delivered_at < UTC_TIMESTAMP(6) - INTERVAL 7 DAY
  AND claim_token IS NULL;
```

执行删除前另行确认 SQL 的数据库、表和相同条件，单次 DELETE 必须有 LIMIT；不要使用 TRUNCATE、级联删除整个活动或直接删除幂等记录。正式数据若未来需要到期处理，先导出、通知、获得负责人确认，再做包含外键依赖和恢复方案的独立变更。
