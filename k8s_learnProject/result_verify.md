
══════════════════════════════════════════════════════════
  1. Namespace 与全局资源总览
══════════════════════════════════════════════════════════
[✓] 所有命名空间
NAME                 STATUS   AGE
default              Active   45m
ingress-nginx        Active   40m
kube-node-lease      Active   45m
kube-public          Active   45m
kube-system          Active   45m
learn-space          Active   27m
local-path-storage   Active   45m
[✓] learn-space 命名空间下的所有资源
NAME                                READY   STATUS      RESTARTS        AGE
pod/count-reporter-29736685-27xq6   0/1     Completed   0               2m10s
pod/count-reporter-29736686-cgf86   0/1     Completed   0               70s
pod/count-reporter-29736687-jjgz9   0/1     Completed   0               10s
pod/init-counter-7nwhj              0/1     Completed   0               9m43s
pod/node-info-h46vl                 1/1     Running     0               27m
pod/rbac-test                       0/1     Completed   0               9m43s
pod/redis-0                         1/1     Running     0               27m
pod/web-6bff565cfd-txkfz            2/2     Running     2 (9m45s ago)   9m47s
pod/web-6bff565cfd-zfr7f            2/2     Running     2 (9m26s ago)   9m28s

NAME                   TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
service/redis          ClusterIP   None            <none>        6379/TCP       27m
service/web            ClusterIP   10.96.124.78    <none>        80/TCP         27m
service/web-nodeport   NodePort    10.96.187.124   <none>        80:30080/TCP   27m

NAME                       DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
daemonset.apps/node-info   1         1         1       1            1           <none>          27m

NAME                  READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/web   2/2     2            2           27m

NAME                             DESIRED   CURRENT   READY   AGE
replicaset.apps/web-5c467cdd7f   0         0         0       27m
replicaset.apps/web-6bff565cfd   2         2         2       9m47s

NAME                     READY   AGE
statefulset.apps/redis   1/1     27m

NAME                                      REFERENCE        TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
horizontalpodautoscaler.autoscaling/web   Deployment/web   <unknown>/70%   2         5         2          27m

NAME                           SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
cronjob.batch/count-reporter   */1 * * * *   False     0        10s             27m

NAME                                COMPLETIONS   DURATION   AGE
job.batch/count-reporter-29736685   1/1           4s         2m10s
job.batch/count-reporter-29736686   1/1           4s         70s
job.batch/count-reporter-29736687   1/1           4s         10s
job.batch/init-counter              1/1           5s         9m43s

══════════════════════════════════════════════════════════
  2. ConfigMap / Secret / PVC（配置与存储）
══════════════════════════════════════════════════════════
[✓] ConfigMap (非敏感配置)
NAME               DATA   AGE
kube-root-ca.crt   1      27m
web-config         4      27m
web-config-files   1      27m
--- web-config 内容 ---
{"PORT":"8080","REDIS_URL":"redis://redis:6379","THEME":"dark","TITLE":"K8s 访客计数器 (学习项目)"}
[✓] Secret (敏感数据, 注意 base64 编码)
NAME        TYPE     DATA   AGE
db-secret   Opaque   2      27m
--- db-secret 解码后的 DB_USER ---
learnadmin
[✓] PersistentVolumeClaim (持久存储)
NAME           STATUS    VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
data-redis-0   Bound     pvc-0548cb0f-40e8-4e15-bbf0-fb5c7a40aa48   256Mi      RWO            standard       27m
redis-data     Pending                                                                        standard       27m

══════════════════════════════════════════════════════════
  3. Pod 状态与标签（探针/资源/调度）
══════════════════════════════════════════════════════════
NAME                            READY   STATUS      RESTARTS        AGE     IP            NODE                      NOMINATED NODE   READINESS GATES
count-reporter-29736685-27xq6   0/1     Completed   0               2m10s   10.244.0.61   k8s-learn-control-plane   <none>           <none>
count-reporter-29736686-cgf86   0/1     Completed   0               70s     10.244.0.62   k8s-learn-control-plane   <none>           <none>
count-reporter-29736687-jjgz9   0/1     Completed   0               10s     10.244.0.65   k8s-learn-control-plane   <none>           <none>
init-counter-7nwhj              0/1     Completed   0               9m43s   10.244.0.42   k8s-learn-control-plane   <none>           <none>
node-info-h46vl                 1/1     Running     0               27m     10.244.0.13   k8s-learn-control-plane   <none>           <none>
rbac-test                       0/1     Completed   0               9m43s   10.244.0.43   k8s-learn-control-plane   <none>           <none>
redis-0                         1/1     Running     0               27m     10.244.0.16   k8s-learn-control-plane   <none>           <none>
web-6bff565cfd-txkfz            2/2     Running     2 (9m45s ago)   9m47s   10.244.0.41   k8s-learn-control-plane   <none>           <none>
web-6bff565cfd-zfr7f            2/2     Running     2 (9m26s ago)   9m28s   10.244.0.44   k8s-learn-control-plane   <none>           <none>

══════════════════════════════════════════════════════════
  4. Service 与端点（网络发现）
══════════════════════════════════════════════════════════
NAME           TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
redis          ClusterIP   None            <none>        6379/TCP       27m
web            ClusterIP   10.96.124.78    <none>        80/TCP         27m
web-nodeport   NodePort    10.96.187.124   <none>        80:30080/TCP   27m
[✓] web Service 的 Endpoints (负载均衡到哪些 Pod)
NAME   ENDPOINTS                           AGE
web    10.244.0.41:8080,10.244.0.44:8080   27m

══════════════════════════════════════════════════════════
  5. 应用输出 — 访问计数器主页
══════════════════════════════════════════════════════════
[✓] 通过 ClusterIP Service 内部访问 (展示 Pod 身份/计数/配置注入)
你是第 <span class="count">17</span> 位访客
Redis (StatefulSet)
Secret)
Pod: web-6bff565cfd-zfr7f
NS: learn-space

[✓] 通过 NodePort 访问 (节点端口 30080)
你是第 <span class="count">18</span> 位访客

[✓] /healthz (liveness) 与 /readyz (readiness) 输出
healthz: {"status":"alive","uptime":570}
readyz: {"status":"ready","redis":true}
pod "curl-test2" deleted

[✓] /metrics (Prometheus 指标)
# HELP learn_visits_total 访客总数
# TYPE learn_visits_total counter
learn_visits_total 18
# HELP learn_http_requests_total HTTP 请求总数
# TYPE learn_http_requests_total counter
learn_http_requests_total 194

══════════════════════════════════════════════════════════
  6. StatefulSet — Redis 有状态应用
══════════════════════════════════════════════════════════
NAME    READY   AGE
redis   1/1     27m
[✓] Redis 数据持久化验证 (PVC)
NAME           STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
data-redis-0   Bound    pvc-0548cb0f-40e8-4e15-bbf0-fb5c7a40aa48   256Mi      RWO            standard       27m

══════════════════════════════════════════════════════════
  7. Deployment 副本与滚动更新
══════════════════════════════════════════════════════════
NAME   READY   UP-TO-DATE   AVAILABLE   AGE
web    2/2     2            2           27m
[✓] 滚动更新历史 (用于回滚)
deployment.apps/web 
REVISION  CHANGE-CAUSE
1         <none>
2         <none>


══════════════════════════════════════════════════════════
  8. DaemonSet — 每节点一个 Pod
══════════════════════════════════════════════════════════
NAME        DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
node-info   1         1         1       1            1           <none>          27m
[✓] DaemonSet Pod 日志 (节点信息采集)
11:26:53 node=node-info-h46vl loadavg=0.75
11:27:03 node=node-info-h46vl loadavg=0.79
11:27:13 node=node-info-h46vl loadavg=1.61

══════════════════════════════════════════════════════════
  9. Job / CronJob — 批处理与定时任务
══════════════════════════════════════════════════════════
[✓] Job 执行结果
NAME                      COMPLETIONS   DURATION   AGE
count-reporter-29736685   1/1           4s         2m18s
count-reporter-29736686   1/1           4s         78s
count-reporter-29736687   1/1           4s         18s
init-counter              1/1           5s         9m51s
[job] 初始化 Redis 计数器...
OK
OK
[job] 当前 visits=0
[job] 初始化完成
[✓] CronJob 调度状态
NAME             SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
count-reporter   */1 * * * *   False     0        18s             27m

══════════════════════════════════════════════════════════
  10. HPA — 自动扩缩容配置
══════════════════════════════════════════════════════════
NAME   REFERENCE        TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
web    Deployment/web   <unknown>/70%   2         5         2          27m
[✓] 当前指标 (需 metrics-server)
NAME                   CPU(cores)   MEMORY(bytes)   
node-info-h46vl        1m           0Mi             
redis-0                6m           8Mi             
web-6bff565cfd-txkfz   1m           8Mi             
web-6bff565cfd-zfr7f   1m           8Mi             

══════════════════════════════════════════════════════════
  11. Ingress — 七层路由
══════════════════════════════════════════════════════════
NAME          CLASS   HOSTS             ADDRESS     PORTS   AGE
web-ingress   nginx   k8s-learn.local   localhost   80      27m
[✓] 通过 Ingress 访问 (需配 /etc/hosts: k8s-learn.local -> 127.0.0.1)
你是第 <span class="count">19</span> 位访客

══════════════════════════════════════════════════════════
  12. RBAC — 权限验证
══════════════════════════════════════════════════════════
NAME                     SECRETS   AGE
serviceaccount/default   0         27m
serviceaccount/reader    0         27m

NAME                                        CREATED AT
role.rbac.authorization.k8s.io/pod-reader   2026-07-16T10:59:21Z

NAME                                                   ROLE              AGE
rolebinding.rbac.authorization.k8s.io/reader-binding   Role/pod-reader   27m
[✓] rbac-test Pod 的输出 (演示最小权限)
web-5c467cdd7f-bq2p8            1/2     CrashLoopBackOff    8 (90s ago)   18m
web-5c467cdd7f-x6vv2            1/2     CrashLoopBackOff    8 (93s ago)   18m
web-6bff565cfd-txkfz            1/2     CrashLoopBackOff    1 (6s ago)    8s
[rbac] 尝试删除 pod (应被拒绝):
Error from server (Forbidden): pods "web-0" is forbidden: User "system:serviceaccount:learn-space:reader" cannot delete resource "pods" in API group "" in the namespace "learn-space"
[rbac] 验证完成

══════════════════════════════════════════════════════════
  13. NetworkPolicy — 网络隔离
══════════════════════════════════════════════════════════
NAME                   POD-SELECTOR                                    AGE
redis-allow-web-only   app=redis,app.kubernetes.io/part-of=k8s-learn   27m

══════════════════════════════════════════════════════════
  验证完成！
══════════════════════════════════════════════════════════
[✓] 多容器 Pod (sidecar) 日志:
2026-07-16T11:27:13.550Z GET /readyz
2026-07-16T11:27:13.550Z GET /healthz
2026-07-16T11:27:18.549Z GET /readyz

常用调试命令:
  kubectl -n learn-space describe pod <pod-name>   # 排查 Pod 问题
  kubectl -n learn-space logs -f deploy/web         # 看实时日志
  kubectl -n learn-space exec -it deploy/web -- sh  # 进入容器
  kubectl -n learn-space rollout undo deploy/web    # 回滚上一版本
