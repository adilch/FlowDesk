python3 - "$HOME/flowdesk/1/Untitled-1/flowdesk.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("physics.time:", d["physics"]["time"])
print("physics.free_surface set:", d["physics"]["free_surface"] is not None)
r = d["run"]
print("run.write_interval_steady:", r.get("write_interval_steady"))
print("run.purge_write:", r.get("purge_write"), "purge_transient:", r.get("purge_write_transient"))
PY
