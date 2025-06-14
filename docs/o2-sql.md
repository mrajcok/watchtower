# O2 SQL
For some projects you may want to chart data based on a timestamp that is
different from the log timestamp. E.g., you might process some kind
of data that comes in, say, every 5 minutes.  

If you instrument your logs with a data timestamp--e.g.,
```
dtime=2025-04-27T03:25:00
```
you can then plot a metric--e.g., job duration, data volume, etc.--for each 5-minute bucket with
O2 custom SQL as follows:
```
SELECT cast(dtime as timestamp) as "data time", CAST(some_metric AS FLOAT) AS metric FROM "my_logs"
 where tag = 'job-metrics'
```
If you process that data in multiple jobs per 5-minute bucket you can plot
aggregations--e.g., sum, avg, etc.--of the data for each 5-minute bucket:
```
SELECT to_timestamp(
        CAST(EXTRACT(EPOCH FROM CAST(dtime AS TIMESTAMP)) / 300 AS INTEGER) * 300
    ) AS dtime_bucket,
    AVG(CAST(cpu AS INTEGER)) AS avg_cpu
FROM "watchtower_logs"
WHERE tag = 'metrics2'
GROUP BY dtime_bucket
order by dtime_bucket
```
`date_trunc` is easier to user, but it can only be used to aggregate by minute, hour or day:
```
SELECT date_trunc('hour', CAST(dtime AS TIMESTAMP)) AS dtime_hour,
    AVG(CAST(cpu AS INTEGER)) AS avg_cpu
FROM  watchtower_logs
WHERE tag = 'metrics2'
GROUP BY dtime_hour
ORDER BY dtime_hour
```
While DataFusion has DATE_TRUNC, it typically truncates to standard units (minute, hour,
day, etc.) and doesn't directly support arbitrary intervals like '5 minutes' within the
function itself. So, the method using EXTRACT(EPOCH FROM ...) and integer arithmetic
is often the standard SQL way to achieve this kind of arbitrary time bucketing when
a dedicated function isn't available--so says AI.
