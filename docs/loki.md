# Fluent Bit and Loki
To view what Fluent Bit outputs to Loki, query Loki's api:
```bash
$ curl -sG 'http://localhost:3100/loki/api/v1/query_range' -d 'query={service_name="fluent-bit"}' -d 'direction=backward' -d 'limit=1' | jq  '.data.result'   # use jq -c to get a single line of output
```
Here's a sample:
```json
    "stream": {
      "detected_level": "unknown",
      "job": "fluent-bit",
      "service_name": "fluent-bit"
    },
    "values": [
      [
        "1744763492225733000",
        "{\"_MACHINE_ID\":\"eb536e5c3d6c41f796c47b2277c942b2\",\"_HOSTNAME\":\"Mark\",\"PRIORITY\":\"6\",\"_UID\":\"0\",\"_GID\":\"0\",\"_SYSTEMD_SLICE\":\"system.slice\",\"_TRANSPORT\":\"journal\",\"_CAP_EFFECTIVE\":\"1ffffffffff\",\"_COMM\":\"dockerd\",\"_EXE\":\"/usr/bin/dockerd\",\"_CMDLINE\":\"/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock\",\"_SYSTEMD_CGROUP\":\"/system.slice/docker.service\",\"_SYSTEMD_UNIT\":\"docker.service\",\"_BOOT_ID\":\"63f8b3d0deae4ecfa8f5bd6c55f922ee\",\"_PID\":\"280\",\"_SYSTEMD_INVOCATION_ID\":\"1455fa72254b46258e3cefd60d576911\",\"IMAGE_NAME\":\"watchtower-base\",\"CONTAINER_NAME\":\"watchtower-watchtower-1\",\"CONTAINER_TAG\":\"watchtower\",\"SYSLOG_IDENTIFIER\":\"watchtower\",\"CONTAINER_LOG_ORDINAL\":\"17\",\"MESSAGE\":\"level=debug pid=9 src=db_connection_pool.py:168 tag=dbconn-added msg=\\\"new connection put into pool by background task\\\" conn_id=3 resource_id=sqlite_traffic\",\"CONTAINER_ID\":\"f2de2392667f\",\"CONTAINER_ID_FULL\":\"f2de2392667fb3c88e18103ee1c18adc56e22e81b8d3e7e2e9f688f6c821d5bf\",\"CONTAINER_LOG_EPOCH\":\"8528a05aaf489ddfc48d351ea21d8cf672e28c2f6dfb3481996b176b91b27d04\",\"SYSLOG_TIMESTAMP\":\"2025-04-16T00:31:32.225696771Z\",\"_SOURCE_REALTIME_TIMESTAMP\":\"1744763492225709\"}"
```
The Fluent Bit Loki driver apparently adds the following (undocumented) fields to stream:
- detected_level
- service_name

The "stream" section does not indicate which of these fields are Loki labels and which are
[structured metadata](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/).
To determine which fields are labels
```
$ curl -sG "http://localhost:3100/loki/api/v1/labels" | jq
```
```json
  "status": "success",
  "data": [
    "__stream_shard__",  // this is added by Loki
    "job",
    "service_name"
```

fluent-bit-*-loki.yaml addresses the following issues with the out-of-the-box pipeline:
- specify the following labels: service_name (used/required by Grafana drilldown), tag, resource_id
- remove most of the journald fields
- parse certain fields out of the log message and make them structured metadata
- parse the remaining key=value fields

Here's the reworked output that Fluent Bit sends to Loki:
```bash
$ curl -sG 'http://localhost:3100/loki/api/v1/query_range' -d 'query={service_name="fluent-bit"}' -d 'direction=backward' -d 'limit=1' | jq  '.data.result'   # use jq -c to get a single line of output
```
```json
TBD
```

# Storage
Loki will index the labels and store the log contents (on local disk).
You should reconfigure Loki to use shared storage or object storage (e.g., S3 or Ceph
object storage) if you have that available.

# LogQL
Loki can then be queried with [LogQL](https://grafana.com/docs/loki/latest/query/) using
[LogCLI](https://grafana.com/docs/loki/latest/query/logcli/) or in
[Grafana](https://grafana.com/docs/loki/latest/visualize/grafana/).

LogQL has an annoying quirk that to plot raw values in a Grafana time series panel requires the
use of aggregation, unlike, say how Kibana Lens works with Elasticsearch work or O2 works with SQL.

TBD show some samples
```
sum_over_time({service_name="watchtower", tag="metrics"}|logfmt | keep cpu| unwrap cpu [$__auto])
```
