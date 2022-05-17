#!/usr/bin/env python3

import socket
import json
import logging
import argparse
import nagiosplugin
import sys

from nagiosplugin import (
    Check,
    Context,
    Metric,
    Performance,
    Resource,
    ScalarContext,
    Summary,
)
from nagiosplugin.state import Critical, Ok, Unknown, Warn

logger = logging.getLogger(__name__)


class ApiError(Exception):
    pass


class TeamRedMinerApi:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(self, command):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout)
            client.connect((self.host, self.port))
            r = {"command": command}
            client.sendall(json.dumps(r).encode())
            response = []
            while True:
                data = client.recv(4096)
                if data:
                    response.append(data.decode("utf-8"))
                else:
                    break
            response = json.loads("".join(response))
            self.raise_for_status(response)
            logger.debug(response)
            response.pop("STATUS")
            response.pop("id")
            return response[list(response.keys())[0]]

    @staticmethod
    def raise_for_status(response):
        for r in response["STATUS"]:
            status = r["STATUS"]
            code = r["Code"]
            message = r["Msg"]
            if status in ["W", "E", "F"]:
                raise ApiError(f"API error: {message} (code {code})")


class TeamRedMiner(Resource):
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout

    def probe(self):
        client = TeamRedMinerApi(host=self.host, port=self.port, timeout=self.timeout)
        metrics = []

        summary = client.request("summary")[0]
        if "MHS 30s" in summary:
            hashrate = summary["MHS 30s"]
            logger.info(f"Hashrate is {hashrate} MH/s")
            metrics.append(Metric("hashrate", hashrate, uom="MH/s", context="hashrate"))

        if "Elapsed" in summary:
            uptime = summary["Elapsed"]
            seconds = "seconds" if uptime > 1 else "second"
            logger.info(f"Uptime is {uptime} {seconds}")
            metrics.append(Metric("uptime", uptime, uom="s", context="uptime"))

        devices = client.request("devs")
        for device in devices:
            if "GPU" in device:
                id = device["GPU"]

                if "Status" in device:
                    alive = device["Status"] == "Alive"
                    if alive:
                        logger.info(f"GPU {id} is alive")
                    else:
                        logger.info(f"GPU {id} is dead!")
                    metrics.append(Metric(f"alive_{id}", alive, context="alive"))

                if "Temperature" in device:
                    temperature = device["Temperature"]
                    logger.info(f"GPU {id}: temperature is {temperature}C")
                    metrics.append(
                        Metric(
                            f"temperature_{id}",
                            temperature,
                            uom="C",
                            context="temperature",
                        )
                    )

                if "TemperatureMem" in device:
                    temperature = device["TemperatureMem"]
                    logger.info(f"GPU {id}: memory temperature is {temperature}C")
                    metrics.append(
                        Metric(
                            f"memory_temperature_{id}",
                            temperature,
                            uom="C",
                            context="temperature",
                        )
                    )

        return metrics


class BelowThresholdContext(Context):
    def __init__(self, name, warning=None, critical=None):
        super().__init__(name)
        self.warning = warning
        self.critical = critical

    def evaluate(self, metric, resource):
        unit = None
        if metric.uom:
            unit = metric.uom
        if self.critical and metric.value <= self.critical:
            return self.result_cls(
                Critical, f"{metric.value}<={self.critical}{unit}", metric
            )
        elif self.warning and metric.value <= self.warning:
            return self.result_cls(
                Warn, f"{metric.value}<={self.warning}{unit}", metric
            )
        else:
            return self.result_cls(Ok, None, metric)

    def performance(self, metric, resource):
        return Performance(
            metric.name,
            metric.value,
            metric.uom,
            self.warning,
            self.critical,
            metric.min,
            metric.max,
        )


class BooleanContext(Context):
    def __init__(self, name, expected=True, warning=False, critical=False):
        super().__init__(name)
        self.expected = expected
        self.warning = warning
        self.critical = critical

    def evaluate(self, metric, resource):
        if not metric.value is self.expected:
            result_type = Ok
            if self.critical:
                result_type = Critical
            elif self.warning:
                result_type = Warn
            return self.result_cls(
                result_type, f"{metric.name} is not {self.expected}", metric
            )
        else:
            return self.result_cls(Ok, None, metric)


class TeamRedMinerSummary(Summary):
    def problem(self, results):
        return ", ".join(
            [
                f"{result.metric.name} {result.state}: {result.hint}"
                for result in results
                if str(result.state) != "ok"
            ]
        )


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-v",
        "--verbose",
        dest="loglevel",
        action="store_const",
        const=logging.INFO,
        help="Print more output",
    )
    parser.add_argument(
        "-d",
        "--debug",
        dest="loglevel",
        action="store_const",
        const=logging.DEBUG,
        default=logging.WARNING,
        help="Print even more output",
    )
    parser.add_argument(
        "--version",
        dest="show_version",
        action="store_true",
        help="Print version and exit",
    )

    parser.add_argument(
        "--host",
        dest="host",
        type=str,
        help="Host address of TeamRedMiner API",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        dest="port",
        type=int,
        help="Port of TeamRedMiner API",
        default=4028,
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=int,
        help="Timeout, in seconds, when requesting TeamRedMiner API",
        default=1,
    )

    parser.add_argument(
        "--hashrate-warning",
        dest="hashrate_warning",
        type=int,
        help="Raise warning if hashrate goes below this threshold",
    )
    parser.add_argument(
        "--hashrate-critical",
        dest="hashrate_critical",
        type=int,
        help="Raise critical if hashrate goes below this threshold",
    )
    parser.add_argument(
        "--uptime-warning",
        dest="uptime_warning",
        type=int,
        help="Raise warning if uptime goes below this threshold",
    )
    parser.add_argument(
        "--uptime-critical",
        dest="uptime_critical",
        type=int,
        help="Raise critical if uptime goes below this threshold",
    )
    parser.add_argument(
        "--temperature-warning",
        dest="temperature_warning",
        type=int,
        help="Raise warning if temperature goes over this threshold",
        default=70,
    )
    parser.add_argument(
        "--temperature-critical",
        dest="temperature_critical",
        type=int,
        help="Raise critcal if temperature goes over this threshold",
        default=90,
    )
    parser.add_argument(
        "--memory-temperature-warning",
        dest="memory_temperature_warning",
        type=int,
        help="Raise warning if memory temperature goes over this threshold",
        default=90,
    )
    parser.add_argument(
        "--memory-temperature-critical",
        dest="memory_temperature_critical",
        type=int,
        help="Raise critcal if memory temperature goes over this threshold",
        default=110,
    )

    args = parser.parse_args()
    return args


def setup_logging(args):
    logging.basicConfig(format="%(levelname)s: %(message)s", level=args.loglevel)


def show_version():
    print("1.0.0")


def main():
    args = parse_arguments()
    setup_logging(args)

    if args.show_version:
        show_version()
        return

    try:
        check = Check(
            TeamRedMiner(host=args.host, port=args.port, timeout=args.timeout),
            BelowThresholdContext(
                "hashrate",
                warning=args.hashrate_warning,
                critical=args.hashrate_critical,
            ),
            BelowThresholdContext(
                "uptime", warning=args.uptime_warning, critical=args.uptime_critical
            ),
            ScalarContext(
                "temperature",
                warning=args.temperature_warning,
                critical=args.temperature_critical,
            ),
            BooleanContext("alive", expected=True, critical=True),
            TeamRedMinerSummary(),
        )
        check.main()
    except Exception as err:
        print(f"Failed to execute check: {str(err)}")
        logger.debug(err, exc_info=True)
        sys.exit(Unknown.code)


if __name__ == "__main__":
    main()
