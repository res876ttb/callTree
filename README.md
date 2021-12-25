# callTree

## Prerequisite

* cscope tags with compression
  * ASCII mode is not support currently

## Usage

```
usage: calltree [-h] [-p PATH] [-b BLACKLIST] [-o OUTPUT] [-d DEPTH] [-v] [-n]
                [-g]
                symbols

positional arguments:
  symbols               The root symbols of caller tree. If you want to build
                        multiple trees at a time, use comma without space to
                        seperate each symbol. For example, `symbol1,symbol2`

optional arguments:
  -h, --help            show this help message and exit
  -p PATH, --path PATH  Path to the cscope.out file or GPATH/GRTAGS/GTAGS with
                        sqlite3 format.
  -b BLACKLIST, --blacklist BLACKLIST
                        List of black list. Use comma to seperate each symbol
                        with space. Regex matching is supported. For example,
                        `DEBUG,DEBUG_\w+`
  -o OUTPUT, --output OUTPUT
                        The output HTML file name.
  -d DEPTH, --depth DEPTH
                        Max depth of result. Default is 900, which is also
                        maximal value.
  -v, --verbose         Show more log for debugging.
  -n, --no_position     Whether NOT to show ref file and line number.
  -g, --background      Whether NOT to print output to stdout.
```

## TODO

- [x] Add cscope support
- [x] Generate static HTML for easy tracing
- [ ] Interactive web for code tracing (Pending)

