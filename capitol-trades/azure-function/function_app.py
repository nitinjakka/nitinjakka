"""Azure Functions app: Nancy Pelosi trade-disclosure monitor.

- pelosi_timer: runs every 6 hours, checks for new filings, emails on new ones.
- pelosi_run:   HTTP endpoint (function-key protected) for manual runs/testing.
                Query params: send=0 to skip email, delay=N seconds between
                the 3 verification fetches (default 45).
"""
import json
import logging

import azure.functions as func

import pelosi_core

app = func.FunctionApp()


@app.timer_trigger(schedule="0 0 */6 * * *", arg_name="timer",
                   run_on_startup=False, use_monitor=True)
def pelosi_timer(timer: func.TimerRequest) -> None:
    summary = pelosi_core.run_monitor()
    logging.info("pelosi_timer summary: %s", json.dumps(summary, default=str))


@app.route(route="pelosi_run", auth_level=func.AuthLevel.FUNCTION)
def pelosi_run(req: func.HttpRequest) -> func.HttpResponse:
    send = req.params.get("send", "1") != "0"
    delay = int(req.params.get("delay", "45"))
    summary = pelosi_core.run_monitor(delay=delay, send=send)
    return func.HttpResponse(json.dumps(summary, indent=2, default=str),
                             mimetype="application/json")
