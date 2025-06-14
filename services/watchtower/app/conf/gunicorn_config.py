from prometheus_client import multiprocess
import sys

def child_exit(server, worker):
    print(f"gunicorn worker {worker.pid} has exited", file=sys.stderr, flush=True)
    multiprocess.mark_process_dead(worker.pid)
