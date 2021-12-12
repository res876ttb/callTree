# callTree

## Prerequisite

* GNU global installed on the system
* GNU global should be compiled with sqlite3 support
* GTAGS/GRTAGS/GPATH shuold be generated with `--sqlite3` options

## Usage

usage: `callTree.py [-h] [--path PATH] [--blacklist BLACKLIST] [-v] [--show_position] symbols`

positional arguments:
  symbols               The root symbols of caller tree. If you want to build multiple trees at a time, use comma without space to seperate
                        each symbol. For example, `symbol1,symbol2`

optional arguments:
  -h, --help            show this help message and exit
  --path PATH           Path to the GPATH/GRTAGS/GTAGS with sqlite3 format.
  --blacklist BLACKLIST
                        List of black list. Use comma to seperate each symbol with space. For example, `DEBUG,RANDOM`
  -v, --verbose         Show more log for debugging.
  --show\_position       Whether to show ref file and line number.

## TODO

- [ ] Add cscope support

