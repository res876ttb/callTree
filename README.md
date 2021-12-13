# callTree

## Prerequisite

* GNU global installed on the system
* GNU global should be compiled with sqlite3 support
* GTAGS/GRTAGS/GPATH shuold be generated with `--sqlite3` options

## Usage

```
usage: calltree [-h] [-p PATH] [-b BLACKLIST] [-v] [-s] [-o OUTPUT] [-g] [-d DEPTH] symbols

positional arguments:
  symbols               The root symbols of caller tree. If you want to build multiple trees at a time, use comma without space to seperate
                        each symbol. For example, `symbol1,symbol2`

optional arguments:
  -h, --help            show this help message and exit
  -p PATH, --path PATH  Path to the GPATH/GRTAGS/GTAGS with sqlite3 format.
  -b BLACKLIST, --blacklist BLACKLIST
                        List of black list. Use comma to seperate each symbol with space. For example, `DEBUG,RANDOM`
  -v, --verbose         Show more log for debugging.
  -s, --show_position   Whether to show ref file and line number.
  -o OUTPUT, --output OUTPUT
                        The output file name.
  -g, --background      Whether NOT to print output to stdout.
  -d DEPTH, --depth DEPTH
                        Max depth of result. If set to -1, then the result is unlimited. Default is -1.
```

## TODO

- [ ] Add cscope support

