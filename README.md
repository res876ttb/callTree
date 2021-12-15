# callTree

## Prerequisite

* GNU global or cscope installed on the system
* GNU global limitations:
  * GNU global should be compiled with sqlite3 support
  * GTAGS/GRTAGS/GPATH shuold be generated with `--sqlite3` options
* cscope limitations: no

## Usage

```
usage: calltree [-h] [-p PATH] [-b BLACKLIST] [-o OUTPUT] [-d DEPTH]
                [-t {global,cscope}] [-v] [-s] [-g]
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
                        The output file name.
  -d DEPTH, --depth DEPTH
                        Max depth of result. If set to -1, then the result is
                        unlimited. Default is -1.
  -t {global,cscope}, --tag_version {global,cscope}
                        Choose tag system you want to use. Available choices:
                        [global(tags generated with sqlite3 support), cscope]
                        Default: cscope.
  -v, --verbose         Show more log for debugging.
  -s, --show_position   Whether to show ref file and line number.
  -g, --background      Whether NOT to print output to stdout.
```

## TODO

- [x] Add cscope support
- [ ] Generate static HTML for easy tracing
- [ ] Interactive web for code tracing

