"""Builds dashboards/lanka-link-vps.json, the Grafana template provisioned on the VPS.

    python infra/monitoring/grafana/build_dashboard.py

Edit panels here rather than in the JSON, then rebuild; Grafana reloads it on its own.
"""

import json
from pathlib import Path

ds = {"type": "prometheus", "uid": "prometheus"}
panels = []
pid = [0]
y = [0]
R = "$__rate_interval"


def nid():
    pid[0] += 1
    return pid[0]


def row(title):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y[0]}, "panels": []})
    y[0] += 1


def stat(title, expr, x, w, unit="none", th=None, desc="", mappings=None, decimals=None):
    p = {"type": "stat", "title": title, "id": nid(), "datasource": ds, "description": desc,
         "gridPos": {"h": 4, "w": w, "x": x, "y": y[0]},
         "targets": [{"refId": "A", "expr": expr, "datasource": ds, "instant": True}],
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                     "colorMode": "value", "graphMode": "none", "textMode": "value", "justifyMode": "center"},
         "fieldConfig": {"defaults": {"unit": unit, "mappings": mappings or [], "color": {"mode": "thresholds"},
                                      "thresholds": {"mode": "absolute", "steps": th or [{"color": "text", "value": None}]}},
                         "overrides": []}}
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    panels.append(p)


def ts(title, targets, x, w, h=8, unit="none", stack=False, desc="", maxv=None, table=False):
    p = {"type": "timeseries", "title": title, "id": nid(), "datasource": ds, "description": desc,
         "gridPos": {"h": h, "w": w, "x": x, "y": y[0]},
         "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": leg, "datasource": ds}
                     for i, (e, leg) in enumerate(targets)],
         "options": {"tooltip": {"mode": "multi", "sort": "desc"},
                     "legend": {"displayMode": "table" if table else "list", "placement": "right" if table else "bottom",
                                "calcs": ["lastNotNull", "max"] if table else []}},
         "fieldConfig": {"defaults": {"unit": unit, "min": 0, "color": {"mode": "palette-classic"},
                                      "custom": {"lineWidth": 2, "fillOpacity": 18 if stack else 0, "showPoints": "never",
                                                 "spanNulls": True, "axisSoftMin": 0,
                                                 "stacking": {"mode": "normal" if stack else "none", "group": "A"}}},
                         "overrides": []}}
    if maxv is not None:
        p["fieldConfig"]["defaults"]["max"] = maxv
    panels.append(p)


GOOD = [{"color": "red", "value": None}, {"color": "green", "value": 1}]
UPDOWN = [{"type": "value", "options": {"0": {"text": "Down", "color": "red"}, "1": {"text": "Up", "color": "green"}}}]


def load(warn, crit):
    return [{"color": "green", "value": None}, {"color": "orange", "value": warn}, {"color": "red", "value": crit}]


ROOT = 'mountpoint="/",fstype!="rootfs"'
IDLE = f'(1 - avg(rate(node_cpu_seconds_total{{mode="idle"}}[{R}]))) * 100'
NICS = 'device!~"lo|veth.*|br-.*|docker.*"'

row("At a glance")
stat("Services healthy", 'sum(probe_success{job="health"})', 0, 3,
     desc="Services whose health endpoint answered on the last probe, out of the count in the next tile.")
stat("Services probed", 'count(probe_success{job="health"})', 3, 3)
stat("Public site", 'min(probe_success{job="public"})', 6, 3, mappings=UPDOWN, th=GOOD,
     desc="The public /healthz fetched through DNS, TLS and the edge, the way a customer reaches it.")
stat("CPU busy", IDLE, 9, 3, unit="percent", th=load(70, 90), decimals=0)
stat("Memory used", "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100", 12, 3,
     unit="percent", th=load(80, 90), decimals=0)
stat("Disk used", f"(1 - node_filesystem_avail_bytes{{{ROOT}}} / node_filesystem_size_bytes{{{ROOT}}}) * 100", 15, 3,
     unit="percent", th=load(75, 85), decimals=0)
stat("Edge requests", f"sum(rate(caddy_http_request_duration_seconds_count[{R}]))", 18, 3, unit="reqps", decimals=1)
stat("Certificate expires in", '(min(probe_ssl_earliest_cert_expiry{job="public"}) - time()) / 86400', 21, 3,
     unit="d", decimals=0,
     th=[{"color": "red", "value": None}, {"color": "orange", "value": 7}, {"color": "green", "value": 14}])
y[0] += 4

row("Host (the VPS)")
ts("CPU by mode", [(f'sum by (mode) (rate(node_cpu_seconds_total{{mode!="idle"}}[{R}])) / scalar(count(count by (cpu) (node_cpu_seconds_total))) * 100', "{{mode}}")],
   0, 8, unit="percent", stack=True, maxv=100,
   desc="Share of all vCPUs, stacked by what they were doing. The gap to 100 is idle.")
ts("Load average", [("node_load1", "1 minute"), ("node_load5", "5 minutes"), ("node_load15", "15 minutes"),
                    ("count(count by (cpu) (node_cpu_seconds_total))", "vCPUs")], 8, 8,
   desc="Runnable processes. Load that stays above the vCPU line means work is queueing.")
ts("Memory", [("node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "Used"),
              ("node_memory_MemAvailable_bytes", "Available")], 16, 8, unit="bytes", stack=True)
y[0] += 8
ts("Network", [(f"sum(rate(node_network_receive_bytes_total{{{NICS}}}[{R}]))", "Received"),
               (f"sum(rate(node_network_transmit_bytes_total{{{NICS}}}[{R}]))", "Sent")], 0, 8, unit="Bps")
ts("Disk throughput", [(f"sum(rate(node_disk_read_bytes_total[{R}]))", "Read"),
                       (f"sum(rate(node_disk_written_bytes_total[{R}]))", "Written")], 8, 8, unit="Bps")
ts("Disk space used", [(f"(1 - node_filesystem_avail_bytes{{{ROOT}}} / node_filesystem_size_bytes{{{ROOT}}}) * 100", "Root filesystem")],
   16, 8, unit="percent", maxv=100)
y[0] += 8

row("Containers")
ts("CPU per container", [(f'topk(10, sum by (name) (rate(container_cpu_usage_seconds_total{{name!=""}}[{R}])))', "{{name}}")],
   0, 12, h=9, unit="short", table=True,
   desc="CPU cores in use by the ten busiest containers. Translation and audio are capped at MODEL_CPUS.")
ts("Memory per container", [('topk(10, sum by (name) (container_memory_working_set_bytes{name!=""}))', "{{name}}")],
   12, 12, h=9, unit="bytes", table=True,
   desc="Working set of the ten largest containers. The two model services keep their weights resident.")
y[0] += 9
ts("Network per container (received)",
   [(f'topk(8, sum by (name) (rate(container_network_receive_bytes_total{{name!=""}}[{R}])))', "{{name}}")],
   0, 12, unit="Bps", table=True)
stat("Containers running", 'count(container_last_seen{name!=""})', 12, 4)
stat("Model services memory", 'sum(container_memory_working_set_bytes{name=~".*-(translation|audio)-.*"})', 16, 4,
     unit="bytes", desc="NLLB-200 and faster-whisper together.")
stat("Stack memory", 'sum(container_memory_working_set_bytes{name=~"lanka-link.*"})', 20, 4, unit="bytes")
y[0] += 8

row("Services")
panels.append({"type": "state-timeline", "title": "Health checks", "id": nid(), "datasource": ds,
               "description": "Each service's health endpoint, probed every 15 seconds from inside the network.",
               "gridPos": {"h": 11, "w": 14, "x": 0, "y": y[0]},
               "targets": [{"refId": "A", "expr": 'probe_success{job="health"}', "legendFormat": "{{service}}", "datasource": ds}],
               "options": {"showValue": "never", "rowHeight": 0.8, "mergeValues": True, "alignValue": "left",
                           "legend": {"showLegend": False}},
               "fieldConfig": {"defaults": {"mappings": UPDOWN, "color": {"mode": "thresholds"},
                                            "thresholds": {"mode": "absolute", "steps": GOOD}}, "overrides": []}})
ts("Health check time", [('probe_duration_seconds{job="health"}', "{{service}}")], 14, 10, h=11, unit="s", table=True,
   desc="How long each health endpoint took to answer.")
y[0] += 11

row("Edge (Caddy)")
ts("Requests by status", [(f"sum by (code) (rate(caddy_http_request_duration_seconds_count[{R}]))", "{{code}}")],
   0, 8, unit="reqps", stack=True)
q = "histogram_quantile({}, sum by (le) (rate(caddy_http_request_duration_seconds_bucket[{}])))"
ts("Response time", [(q.format(0.5, R), "p50"), (q.format(0.95, R), "p95"), (q.format(0.99, R), "p99")], 8, 8, unit="s",
   desc="Every request through the edge, pages and API together.")
ts("Server errors", [(f'(sum(rate(caddy_http_request_duration_seconds_count{{code=~"5.."}}[{R}])) or vector(0)) / sum(rate(caddy_http_request_duration_seconds_count[{R}])) * 100', "5xx share")],
   16, 8, unit="percent", desc="Share of requests answered with a 5xx. The EdgeErrors alert fires above 5 percent.")
y[0] += 8
panels.append({"type": "alertlist", "title": "Alerts", "id": nid(), "gridPos": {"h": 6, "w": 24, "x": 0, "y": y[0]},
               "options": {"viewMode": "list", "groupMode": "default", "maxItems": 20, "sortOrder": 1,
                           "dashboardAlerts": False, "alertInstanceLabelFilter": "", "datasource": "Prometheus",
                           "stateFilter": {"firing": True, "pending": True, "noData": False, "normal": False, "error": True}}})

dash = {"uid": "lanka-link-vps", "title": "Lanka Link: VPS and services", "tags": ["lanka-link", "vps"],
        "timezone": "browser", "schemaVersion": 39, "version": 1, "editable": True, "graphTooltip": 1,
        # Auto-refresh off by default: 31 panels every 30 s is real work for a 2 vCPU box, and a
        # refresh cancels queries that have not finished. Turn it on from the time picker.
        "refresh": "", "time": {"from": "now-1h", "to": "now"}, "templating": {"list": []},
        "annotations": {"list": []}, "panels": panels,
        "description": "The production VPS: host resources, every container, each service's health check and the edge. "
                       "Provisioned from infra/monitoring/grafana/dashboards in the repo."}
out = Path(__file__).with_name("dashboards") / "lanka-link-vps.json"
with open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(dash, indent=2) + "\n")
print(len(panels), "panels")
