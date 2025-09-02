## Kubernetes Debugging Agent

An interactive CLI agent that helps troubleshoot Kubernetes Pods that are not Ready. It lists failing Pods, lets you pick one to investigate, and then iteratively asks the model for actions or analysis (describe, logs, get events, etc.).

### Features

- Detects all Pods that are not Ready across all namespaces
- Resolves higher-level controllers per Pod (Deployment, StatefulSet, DaemonSet, Job)
- Interactive chat loop for a selected Pod
- Model-driven actions:
  - Describe Pod / Deployment
  - Get logs (with container picker if multiple containers)
  - Get ConfigMap (as YAML)
  - Get events
- Remediation output formatted with tidy bulleting
- Quick Pod switching in-session via Ctrl+n

### Requirements

- Python 3.10+
- Access to a Kubernetes cluster (kubeconfig or in-cluster config)
- Environment variable `OPENAI_API_KEY`
- Dependencies (install via pip):
  - `kubernetes`
  - `pydantic`
  - `pydantic-ai`
  - `python-dotenv`
  - `urllib3`

If you use a virtualenv, activate it first. Example:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Set your API key (or use a `.env` file in this directory):

```bash
export OPENAI_API_KEY=sk-... # or use .env
```

Ensure `kubectl` can reach your cluster and your kubeconfig context is correct:

```bash
kubectl get nodes
```

### Running inside a Kubernetes cluster (in-cluster config)

This agent can also run from a Pod inside your cluster. It automatically tries local kubeconfig first and falls back to in-cluster config (ServiceAccount token mounted at `/var/run/secrets/kubernetes.io/serviceaccount`).

Requirements when running in-cluster:

- A `ServiceAccount` bound to a `Role`/`ClusterRole` with permissions to read Pods, ReplicaSets, Deployments, StatefulSets, DaemonSets, Jobs, Events, and ConfigMaps in the relevant namespaces.
- The Pod should use that `ServiceAccount` (via `spec.serviceAccountName`).

Example minimal RBAC (adjust as needed):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: debugging-agent-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events", "configmaps"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["replicasets", "deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["get", "list", "watch"]
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: debugging-agent
  namespace: your-namespace
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: debugging-agent-reader-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: debugging-agent-reader
subjects:
  - kind: ServiceAccount
    name: debugging-agent
    namespace: your-namespace
```

When deployed in a Pod with this ServiceAccount, the agent will use in-cluster credentials automatically.

### Run

```bash
./agent.py
```

You will see a numbered list of non-ready Pods. Choose one to start an interactive debugging session.

### Controls in the chat session

- Type natural language questions or requests
- Type `exit` (or `quit`) to end the session
- Press `Ctrl+n` to switch to the next failing Pod
- If the model requests logs and the Pod has multiple containers, you’ll be prompted to choose a container

### Notes on output

- For readability, printed command output is truncated in the console view. The full output is still kept in session context used for analysis. You can increase or remove the truncation in `agent.py` if desired.
- The model’s remediation suggestions are pretty-printed with bullets and numbering on separate lines.

### Example Workflows (Boilerplate)

Replace these with your real examples.

#### Example 1: Pod CrashLoopBackOff

```text
1) Start agent and select the failing Pod
2) Ask: "Why is the Pod failing to start?"
3) Follow the model’s request to view logs
4) Inspect error and apply suggested remediation
```

#### Example 2: ImagePullBackOff

```text
1) Start agent and select the Pod with ImagePullBackOff
2) Ask: "What is preventing the image from pulling?"
3) The agent may request `kubectl describe pod` and events
4) Review auth/registry hints and fix credentials or image reference
```
```Bash
❯ ./agent.py
OPENAI_API_KEY environment variable is set

🚨 Failing pods detected:
1. flow-data-mgmt-764bb874f6-c2lw8 (ns=flow, reason=ContainersNotReady)
2. flow-processor-bcb459647-k5fnl (ns=flow, reason=ContainersNotReady)

Select a pod to debug (number): 1

💬 Interactive Debugging Session Started
Type 'exit' to quit. Press CTRL+n to switch to next pod.

👤 You: 

🔄 Switched to pod flow-processor-bcb459647-k5fnl (ns=flow, reason=ContainersNotReady)
👤 You: 

🔄 Switched to pod flow-data-mgmt-764bb874f6-c2lw8 (ns=flow, reason=ContainersNotReady)
👤 You: 

🔄 Switched to pod flow-processor-bcb459647-k5fnl (ns=flow, reason=ContainersNotReady)
👤 You: please describe the pod

🤖 OpenAI requests action: type='DESCRIBE_POD' namespace='flow' name='flow-processor-bcb459647-k5fnl'

📡 Cluster output for DESCRIBE_POD:
Name:             flow-processor-bcb459647-k5fnl
Namespace:        flow
Priority:         0
Service Account:  default
Node:             netops-tkg-cluster-ucf-28mdg-c52g9-7478n/10.100.72.30
Start Time:       Mon, 25 Aug 2025 13:52:09 +0200
Labels:           app.kubernetes.io/instance=netops-flow
                  app.kubernetes.io/name=flow-processor
                  pod-template-hash=bcb459647
Annotations:      hazelcast.secret.checksum: noauth
                  kafka.secret.checksum: noauth
                  prometheus.io/path: /actuator/prometheus
                  prometheus.io/port: 8080
                  prometheus.io/scrape: true
Status:           Pending
IP:               192.168.1.69
IPs:
  IP:           192.168.1.69
Controlled By:  ReplicaSet/flow-processor-bcb459647
Init Containers:
  flow-processor-init:
    Container ID:   containerd://202ddf86719085d621750635238612b8f9c2a314ff09551b2365a04f1df24e69
    Image:          registry:8443/netops/flow/24.3.8-2/flow-processor-init:latest
    Image ID:       registry:8443/netops/flow/24.3.8-2/flow-processor-init@sha256:dcf47253ffaefa550e31256dbccf3deb0b914a1e3e2000a042b90c9d15c3d3ef
    Port:           <none>
    Host Port:      <none>
    State:          Waiting
      Reason:       CrashLoopBackOff
    Last State:     Terminated
      Reason:       Error
      Exit Code:    1
      Started:      Tue, 02 Sep 2025 10:25:18 +0200
      Finished:     Tue, 02 Sep 2025 10:25:26 +0200
    Ready:          False
    Restart Count:  2155
    Limits:
      cpu:     1
      memory:  1Gi
    Requests:
      cpu:     1
      memory:  1Gi
    Environment:
      FLOW_LOG_LEVEL:                   INFO
      VERTICA_HOST:                     dr-host:5433
      VERTICA_BACKUP_HOSTS:             
      VERTICA_CONNECTION_LOAD_BALANCE:  1
      VERTICA_DB:                       drdata
      VERTICA_DB_USERNAME:              <set to the key 'someuser' in secret 'capm-vertica-secret'>  Optional: false
      VERTICA_DB_PASSWORD:              <set to the key 'somepass' in secret 'capm-vertica-secret'>  Optional: false
      JAVA_TOOL_OPTIONS:                -XX:InitialRAMPercentage=50.0 -XX:MaxRAMPercentage=75.0
      KAFKA_PRODUCER_COMPRESSION_TYPE:  snappy
    Mounts:
      /var/run/secrets/kubernetes.io/serviceaccount from kube-api-access-gttj6 (ro)
Containers:
  flow-processor:
    Container ID:   
    Image:          registry:8443/netops/flow/24.3.8-2/flow-processor:latest
    Image ID:       
    Port:           8080/TCP
    Host Port:      0/TCP
    State:          Waiting
      Reason:       PodInitializing
    Ready:          False
    Restart Count:  0
    Limits:
      cpu:     1
      memory:  2Gi
    Requests:
      cpu:      1
      memory:   2Gi
    Liveness:   http-get http://:http/actuator/health/liveness delay=10s timeout=1s period=10s #success=1 #failure=3
    Readiness:  http-get http://:http/actuator/health/readiness delay=10s timeout=1s period=10s #success=1 #failure=3
    Environment:
      FLOW_LOG_LEVEL:                      TRACE
      FLOW_AGGREGATED_RECORD_TOPIC:        2-flow-aggregated-record
      FLOW_APP_MAPPING_RECORD_TOPIC:       2-flow-application-mapping-record
      FLOW_METRICS_FAMILY_TOPIC:           flow-item-facet-service
      FLOW_ATTRIBUTE_UPDATE_RECORD_TOPIC:  flow-attribute-update-record
      NETOPS_IP_DOMAIN_ID:                 2
      VERTICA_HOST:                        dr-host:5433
      VERTICA_BACKUP_HOSTS:                
      VERTICA_CONNECTION_LOAD_BALANCE:     1
      VERTICA_DB:                          somedb
      VERTICA_DB_USERNAME:                 <set to the key 'someuser' in secret 'capm-vertica-secret'>  Optional: false
      VERTICA_DB_PASSWORD:                 <set to the key 'somepass' in secret 'capm-vertica-secret'>  Optional: false
      KAFKA_BOOTSTRAP_SERVERS:             kafka:9092
      KAFKA_SECURITY_PROTOCOL:             SSL
      KAFKA_TLS_KEY_PASSWORD:              <set to the key 'sslKeyPassword' in secret 'netops-kafka-secret'>         Optional: false
      KAFKA_TLS_TRUST_STORE_PASSWORD:      <set to the key 'sslTrustStorePassword' in secret 'netops-kafka-secret'>  Optional: false
      KAFKA_TLS_KEY_STORE_PASSWORD:        <set to the key 'sslKeyStorePassword' in secret 'netops-kafka-secret'>    Optional: false
      KAFKA_FACET_SERVICE_ENABLED:         true
      HAZELCAST_CLUSTER_NAME:              dev
      HAZELCAST_HOSTS:                     hazelcast:5701
      UDAPPMAPPING_ENABLED:                true
      UDAPPMAPPING_POLLING_PERIOD_MS:      90000
      UDAPPMAPPING_POLLING_INIT_DELAY_MS:  0
      KAFKA_GROUP_ID:                      2-flow-processor
      APPMAP_KAFKA_GROUP_ID:               2-flow-processor
      KAFKA_MAX_POLL_RECORDS:              10000
      FLOW_VERTICA_RESOURCE_POOL:          dataload_processing
      VERTICA_FLOW_BATCH_SIZE:             10000
      JAVA_TOOL_OPTIONS:                   -XX:InitialRAMPercentage=50.0 -XX:MaxRAMPercentage=75.0
      KAFKA_PRODUCER_COMPRESSION_TYPE:     snappy
    Mounts:
      /opt/netops/flow/kafka_client_tls/kafka.client.keystore.jks from kafka-ssl-keystore (ro,path="kafka.client.keystore.jks")
      /opt/netops/flow/kafka_client_tls/kafka.client.truststore.jks from kafka-ssl-truststore (ro,path="kafka.client.truststore.jks")
      /var/run/secrets/kubernetes.io/serviceaccount from kube-api-access-gttj6 (ro)
Conditions:
  Type                        Status
  PodReadyToStartContainers   True 
  Initialized                 False 
  Ready                       False 
  ContainersReady             False 
  PodScheduled                True 
Volumes:
  kafka-ssl-truststore:
    Type:        Secret (a volume populated by a Secret)
    SecretName:  netops-kafka-secret
    Optional:    false
  kafka-ssl-keystore:
    Type:        Secret (a volume populated by a Secret)
    SecretName:  netops-kafka-secret
    Optional:    false
  kube-api-access-gttj6:
    Type:                    Projected (a volume that contains injected data from multiple sources)
    TokenExpirationSeconds:  3607
    ConfigMapName:           kube-root-ca.crt
    ConfigMapOptional:       <nil>
    DownwardAPI:             true
QoS Class:                   Guaranteed
Node-Selectors:              <none>
Tolerations:                 node.kubernetes.io/not-ready:NoExecute op=Exists for 300s
                             node.kubernetes.io/unreachable:NoExecute op=Exists for 300s
Events:
  Type     Reason   Age                        From     Message
  ----     ------   ----                       ----     -------
  Warning  BackOff  4m14s (x50579 over 7d20h)  kubelet  Back-off restarting failed container flow-processor-init in pod flow-processor-bcb459647-k5fnl_flow(b9dad5a2-0835-4768-94c6-cdcc636330cf)
  Normal   Pulling  98s (x2156 over 7d20h)     kubelet  Pulling image "registry:8443/netops/flow/24.3.8-2/flow-processor-init:latest"
...

👤 You: why the pods is failing to start?

🤖 OpenAI requests action: type='LOGS' namespace='flow' name='flow-processor-bcb459647-k5fnl'

Multiple containers detected in pod. Select one:
1. flow-processor-init
2. flow-processor
Select a container (number): 1

📡 Cluster output for LOGS:
        at java.base/java.util.stream.ForEachOps$ForEachOp.evaluateSequential(ForEachOps.java:150) ~[na:na]
        at java.base/java.util.stream.ForEachOps$ForEachOp$OfRef.evaluateSequential(ForEachOps.java:173) ~[na:na]
        at java.base/java.util.stream.AbstractPipeline.evaluate(AbstractPipeline.java:234) ~[na:na]
        at java.base/java.util.stream.ReferencePipeline.forEach(ReferencePipeline.java:596) ~[na:na]
        at org.springframework.boot.SpringApplication.callRunners(SpringApplication.java:772) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.run(SpringApplication.java:325) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.run(SpringApplication.java:1361) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.run(SpringApplication.java:1350) ~[spring-boot-3.4.2.jar:3.4.2]
        at com.broadcom.netops.flow.processor.init.FlowProcessorInitApplication.main(FlowProcessorInitApplication.java:26) ~[classes/:na]
Caused by: com.vertica.support.exceptions.NonTransientConnectionException: [Vertica][VJDBC](100176) Failed to connect to host dr-host on port 5433. Reason: Failed to establish a connection to the primary server or any backup address due to network error
        ... 45 common frames omitted
Caused by: java.io.IOException: Failed to establish a connection to the primary server or any backup address due to network error
        at com.vertica.io.VStream.establishConnection(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.io.VStream.<init>(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        ... 45 common frames omitted
Caused by: java.net.ConnectException: Connection refused
        at java.base/sun.nio.ch.Net.connect0(Native Method) ~[na:na]
        at java.base/sun.nio.ch.Net.connect(Net.java:579) ~[na:na]
        at java.base/sun.nio.ch.Net.connect(Net.java:568) ~[na:na]
        at java.base/sun.nio.ch.NioSocketImpl.connect(NioSocketImpl.java:593) ~[na:na]
        at java.base/java.net.SocksSocketImpl.connect(SocksSocketImpl.java:327) ~[na:na]
        at java.base/java.net.Socket.connect(Socket.java:633) ~[na:na]
        ... 47 common frames omitted

2025-09-02T08:25:26.662Z  INFO 1 --- [flow-database-init] [           main] .s.b.a.l.ConditionEvaluationReportLogger : 

Error starting ApplicationContext. To display the condition evaluation report re-run your application with 'debug' enabled.
2025-09-02T08:25:26.741Z ERROR 1 --- [flow-database-init] [           main] o.s.boot.SpringApplication               : Application run failed

java.lang.IllegalStateException: Failed to execute CommandLineRunner
        at org.springframework.boot.SpringApplication.lambda$callRunner$6(SpringApplication.java:795) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.util.function.ThrowingConsumer.accept(ThrowingConsumer.java:66) ~[spring-core-6.2.2.jar:6.2.2]
        at org.springframework.util.function.ThrowingConsumer$1.accept(ThrowingConsumer.java:86) ~[spring-core-6.2.2.jar:6.2.2]
        at org.springframework.boot.SpringApplication.callRunner(SpringApplication.java:796) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.callRunner(SpringApplication.java:787) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.lambda$callRunners$3(SpringApplication.java:772) ~[spring-boot-3.4.2.jar:3.4.2]
        at java.base/java.util.stream.ForEachOps$ForEachOp$OfRef.accept(ForEachOps.java:183) ~[na:na]
        at java.base/java.util.stream.SortedOps$SizedRefSortingSink.end(SortedOps.java:357) ~[na:na]
        at java.base/java.util.stream.AbstractPipeline.copyInto(AbstractPipeline.java:510) ~[na:na]
        at java.base/java.util.stream.AbstractPipeline.wrapAndCopyInto(AbstractPipeline.java:499) ~[na:na]
        at java.base/java.util.stream.ForEachOps$ForEachOp.evaluateSequential(ForEachOps.java:150) ~[na:na]
        at java.base/java.util.stream.ForEachOps$ForEachOp$OfRef.evaluateSequential(ForEachOps.java:173) ~[na:na]
        at java.base/java.util.stream.AbstractPipeline.evaluate(AbstractPipeline.java:234) ~[na:na]
        at java.base/java.util.stream.ReferencePipeline.forEach(ReferencePipeline.java:596) ~[na:na]
        at org.springframework.boot.SpringApplication.callRunners(SpringApplication.java:772) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.run(SpringApplication.java:325) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.run(SpringApplication.java:1361) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.boot.SpringApplication.run(SpringApplication.java:1350) ~[spring-boot-3.4.2.jar:3.4.2]
        at com.broadcom.netops.flow.processor.init.FlowProcessorInitApplication.main(FlowProcessorInitApplication.java:26) ~[classes/:na]
Caused by: com.broadcom.netops.flow.common.exception.FlowException: query to read table flow_application_mapping has failed
        at com.broadcom.netops.flow.processor.init.service.appmapping.cache.AppMappingCacheLoader.readPage(AppMappingCacheLoader.java:100) ~[classes/:na]
        at com.broadcom.netops.flow.processor.init.service.appmapping.cache.AppMappingCacheLoader.loadFromDb(AppMappingCacheLoader.java:73) ~[classes/:na]
        at com.broadcom.netops.flow.processor.init.FlowProcessorInitApplication.run(FlowProcessorInitApplication.java:31) ~[classes/:na]
        at org.springframework.boot.SpringApplication.lambda$callRunner$5(SpringApplication.java:788) ~[spring-boot-3.4.2.jar:3.4.2]
        at org.springframework.util.function.ThrowingConsumer$1.acceptWithException(ThrowingConsumer.java:82) ~[spring-core-6.2.2.jar:6.2.2]
        at org.springframework.util.function.ThrowingConsumer.accept(ThrowingConsumer.java:60) ~[spring-core-6.2.2.jar:6.2.2]
        ... 17 common frames omitted
Caused by: org.springframework.jdbc.CannotGetJdbcConnectionException: Failed to obtain JDBC Connection
        at org.springframework.jdbc.datasource.DataSourceUtils.getConnection(DataSourceUtils.java:84) ~[spring-jdbc-6.2.2.jar:6.2.2]
        at org.springframework.jdbc.core.JdbcTemplate.execute(JdbcTemplate.java:388) ~[spring-jdbc-6.2.2.jar:6.2.2]
        at org.springframework.jdbc.core.JdbcTemplate.query(JdbcTemplate.java:476) ~[spring-jdbc-6.2.2.jar:6.2.2]
        at org.springframework.jdbc.core.JdbcTemplate.query(JdbcTemplate.java:486) ~[spring-jdbc-6.2.2.jar:6.2.2]
        at com.broadcom.netops.flow.processor.init.service.appmapping.cache.AppMappingCacheLoader.readPage(AppMappingCacheLoader.java:97) ~[classes/:na]
        ... 22 common frames omitted
Caused by: java.sql.SQLNonTransientConnectionException: [Vertica][VJDBC](100176) Failed to connect to host dr-host on port 5433. Reason: Failed to establish a connection to the primary server or any backup address due to network error
        at com.vertica.io.ProtocolStream.<init>(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.core.VConnection.connectNodeTask(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.core.VConnection.connectNode(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.core.VConnection.connectTask(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.core.VConnection.connect(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.jdbc.common.BaseConnectionFactory.doConnect(BaseConnectionFactory.java:223) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.jdbc.common.AbstractDriver.connect(AbstractDriver.java:232) ~[vertica-jdbc-23.4.0-0.jar:na]
        at org.apache.tomcat.jdbc.pool.PooledConnection.connectUsingDriver(PooledConnection.java:346) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.PooledConnection.connect(PooledConnection.java:227) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.ConnectionPool.createConnection(ConnectionPool.java:779) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.ConnectionPool.borrowConnection(ConnectionPool.java:707) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.ConnectionPool.init(ConnectionPool.java:506) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.ConnectionPool.<init>(ConnectionPool.java:155) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.DataSourceProxy.pCreatePool(DataSourceProxy.java:118) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.DataSourceProxy.createPool(DataSourceProxy.java:107) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.apache.tomcat.jdbc.pool.DataSourceProxy.getConnection(DataSourceProxy.java:131) ~[tomcat-jdbc-10.1.34.jar:na]
        at org.springframework.jdbc.datasource.DataSourceUtils.fetchConnection(DataSourceUtils.java:160) ~[spring-jdbc-6.2.2.jar:6.2.2]
        at org.springframework.jdbc.datasource.DataSourceUtils.doGetConnection(DataSourceUtils.java:118) ~[spring-jdbc-6.2.2.jar:6.2.2]
        at org.springframework.jdbc.datasource.DataSourceUtils.getConnection(DataSourceUtils.java:81) ~[spring-jdbc-6.2.2.jar:6.2.2]
        ... 26 common frames omitted
Caused by: com.vertica.support.exceptions.NonTransientConnectionException: [Vertica][VJDBC](100176) Failed to connect to host dr-host on port 5433. Reason: Failed to establish a connection to the primary server or any backup address due to network error
        ... 45 common frames omitted
Caused by: java.io.IOException: Failed to establish a connection to the primary server or any backup address due to network error
        at com.vertica.io.VStream.establishConnection(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        at com.vertica.io.VStream.<init>(Unknown Source) ~[vertica-jdbc-23.4.0-0.jar:na]
        ... 45 common frames omitted
Caused by: java.net.ConnectException: Connection refused
        at java.base/sun.nio.ch.Net.connect0(Native Method) ~[na:na]
        at java.base/sun.nio.ch.Net.connect(Net.java:579) ~[na:na]
        at java.base/sun.nio.ch.Net.connect(Net.java:568) ~[na:na]
        at java.base/sun.nio.ch.NioSocketImpl.connect(NioSocketImpl.java:593) ~[na:na]
        at java.base/java.net.SocksSocketImpl.connect(SocksSocketImpl.java:327) ~[na:na]
        at java.base/java.net.Socket.connect(Socket.java:633) ~[na:na]
        ... 47 common frames omitted

...

👤 You: what is the reason of that traceback?

✅ Final Analysis:
Root Cause: The pod 'flow-processor-bcb459647-k5fnl' fails to initialize due to a database connection issue. The logs show a 'NonTransientConnectionException' error indicating that the application is unable to connect to the Vertica database at host 'dr-host' on port 5433. The specific error message is 'Connection refused', which typically means there is no service listening on the specified port or there is a network policy preventing the connection.
Remediation:
Ensure that the Vertica database server is running at 'dr-host' on port 5433 and accessible from this Kubernetes environment. Verify network policies, firewall rules, and database service configurations to allow traffic to this host and port. Additionally, check if the host and port configurations in the pod environment variables are correct and up to date. If the database configuration has changed, update the Kubernetes secrets accordingly.

👤 You: 

🔄 Switched to pod flow-data-mgmt-764bb874f6-c2lw8 (ns=flow, reason=ContainersNotReady)
👤 You: quit
            👋 Exiting debugger.
```

#### Example 3: Pending Pods due to Scheduling

```text
1) Start agent and select a Pending Pod
2) Ask: "Why is this Pod not scheduled?"
3) The agent may request events and node descriptions
4) Review taints/tolerations, resource requests, affinities, or quotas
```

### Troubleshooting

- If the agent keeps prompting without answers, ensure your `OPENAI_API_KEY` is set and network access is allowed.
- If you get Kubernetes client errors, verify `kubectl` access and current context.

### Security

- Be careful when sharing logs and cluster details; outputs may contain sensitive data.
- Use least-privileged kubeconfig credentials when possible.

### License

This project’s license is TBD. Replace this section with your license of choice.