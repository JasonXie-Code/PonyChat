# 部署经验

首先阅读并以 [Backend/deploy/README.md](../Backend/deploy/README.md) 为准。2026-09-13实际目标为本机 P:/PonyChat；CN/USA是入口转发，旧远程发布脚本不代表当前部署目标。

## 发布前

- 查 git 状态、`Backend/.deploy_revision`、`var/local-stack/status.json` 和实际进程。工作区与生产共用，重启可能加载全部后端已改文件。
- 对比部署标记 files 哈希，找出真正变化的运行文件；不把未验证的并行改动带上线。
- 使用 [deploy_scoped_local.py](../scripts/ops/deploy_scoped_local.py) 的清单、expected token、rollback source 和报告参数。先读实现再调用，不照抄旧 token。
- 旧源码要与上一标记哈希一致。Git blob 的LF和工作区CRLF甚至混合换行可能不同；恢复并核验字节，不把当前候选伪装成旧备份。
- 旧版字节确实无法恢复时，不能声称完整回滚已验证。历史一次发布用了明确披露的旧Git源回滚，此例外不应变成默认跳过校验。
- SQLite备份用backup API；不要简单复制活跃数据库主文件忽略WAL。环境备份放忽略的本机目录，不提交。

## 并发和重启

2026-09-13配置：`.env`、`.env.local-stack` 的 `PONYCHAT_HARNESS_CONCURRENCY=20`；`harness_capacity.py` 硬上限20。`test_harness_runtime.py` 验证20个可进入、第21个排队。此为Harness回合上限，不是整个网站连接上限，也不是20路真实负载性能证明。

supervisor会在启动时缓存子进程环境。仅杀掉chat进程可更新代码，却可能仍用旧环境重启。改环境后需要重启supervisor，最后只读取相关进程环境键验证；不要输出全部环境。

`local_stack.py stop` 只是发停止请求，不等待彻底停止。立刻 `Start-ScheduledTask` 可能因旧任务仍Running而不起作用。先确认旧监督进程/子进程退出、任务Ready，再启动 `PonyChat Local Backend Stack` 并验证新PID。不要同时启动第二份生产Backend。

## 发布后

本机 `http://127.0.0.1:5000/api/health`、CN `https://39.101.74.217/api/health`、官网 `https://www.ponychat.org/api/health` 均需成功且deploy_token一致；检查文件哈希及目标功能，提交发布记录。健康成功不等于真实聊天已验证。

发布标记的代码提交和随后仅记录报告的Git HEAD可能不同，这是正常的；先比较实际代码哈希，不仅比较HEAD。
