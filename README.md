# check_teamredminer

Nagios check for [TeamRedMiner miner](https://github.com/todxx/teamredminer).

# Installation

Using pip:

```
python3 -m venv venv
. ./venv/bin/activate
pip install -r requirements.txt
```

Using debian package manager:

```
sudo apt-get install python3-nagiosplugin
```

# Usage

```
./check_teamredminer.py --help
```

# Examples

Nagios NRPE:

```
command[check_teamredminer]=/opt/check_teamredminer/check_teamredminer.py --hashrate-warning 100 --hashrate-critical 90 --uptime-critical 300 --uptime-warning 600
```

# Limitations

This check has been tested on **GPUs** mining **ethash** algorithm.
If you need this check to support more type of hardware mining more algorithms, feel free to contribue.

# Contributing

```
pip install pre-commit
pre-commit run --files check_teamredminer.py
```
