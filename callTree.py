#!/usr/bin/env python3

import argparse
import sqlite3
import os
import sys
import re
import json
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument('symbols', type=str, help='The root symbols of caller tree. If you want to build multiple trees at a time, use comma without space to seperate each symbol. For example, `symbol1,symbol2`')
parser.add_argument('-p', '--path', type=str, default='.', help='Path to the cscope.out file or GPATH/GRTAGS/GTAGS with sqlite3 format.')
parser.add_argument('-b', '--blacklist', type=str, default='', help='List of black list. Use comma to seperate each symbol with space. Regex matching is supported. For example, `DEBUG,DEBUG_\w+`')
parser.add_argument('-o', '--output', type=str, default='calltree.html', help='The output HTML file name.')
parser.add_argument('-d', '--depth', type=int, default=900, help='Max depth of result. Default is 900, which is also maximal value.')
parser.add_argument('-v', '--verbose', action='store_true', help='Show more log for debugging.')
parser.add_argument('-s', '--show_position', action='store_true', help='Whether to show ref file and line number.')
parser.add_argument('-g', '--background', action='store_true', help='Whether NOT to print output to stdout.')
args = parser.parse_args()

BOOL_VERBOSE              = args.verbose
BOOL_SHOW_POSITION        = args.show_position
BOOL_BACKGROUND           = args.background

NUM_MAX_DEPTH             = max(min(args.depth, 900), 1)

STR_TRAVERSED             = '@Traversed'
STR_BLACKLISTED           = '@Blacklisted'
STR_MAX_DEPTH             = '@ReachMaxDepth'
STR_NO_REFERENCE          = '@NoReference'
STR_FILENAME_SYMBOL       = '\t@'
STR_DEFAULT_FILENAME      = 'main.c'
STR_DEFAULT_FUNCTION      = 'main'
STR_DEFAULT_MACRO         = 'macro'

STR_DEFINE_HEAD           = '#'
STR_DEFINE_END_HEAD       = ')'
STR_DEFINITION_HEAD       = '$'
STR_ENUM_HEAD             = 'e'
STR_FILENAME_HEAD         = '@'
STR_FUNCTION_END_HEAD     = '}'
STR_MARK_HEAD             = 'm'
STR_REFERENCE_HEAD        = '`'
STR_STRUCT_HEAD           = 's'
STR_TYPEDEF_HEAD          = 't'
STR_GLOBAL_VARIABLE_HEAD  = 'g'
STR_CLASS_DEFINITION_HEAD = 'c'

LIST_BLACKLIST            = args.blacklist.split(',') if len(args.blacklist) > 0 else []

RE_ISWORD                 = re.compile('[\w\x80\xff]')

class CallTree:
  def __init__(self, symbols):
    # We should find cscope.out under current directory
    if not os.path.exists('cscope.out'):
      print('Cannot find GTAGS')
      sys.exit(1)

    self.symbols = symbols
    self.traversed = {}
    self.trees = {}

    self.loadCscopeDB()
    self.buildDefinitionMap()
    self.buildTree()

  def log(self, *args):
    if BOOL_VERBOSE:
      curTimeStr = str(datetime.now())
      print("[%s]" % curTimeStr, *args)

  def loadCscopeContent(self, fp):
    # 16 most frequent first chars
    dichar1 = " teisaprnl(of)=c"
    # 8 most frequent second chars
    dichar2 = " tnerpla"

    dicode1 = [0 for _ in range(256)]
    dicode2 = [0 for _ in range(256)]

    for i in range(16):
      dicode1[ord(dichar1[i])] = i * 8 + 1
    for i in range(8):
      dicode2[ord(dichar2[i])] = i + 1

    def dicodeCompress(char1, char2):
      return chr((0o200 - 2) + dicode1[ord(char1)] + dicode2[ord(char2)])

    self.decodeMap = {}
    self.encodeMap = {}
    for c1 in dichar1:
      for c2 in dichar2:
        self.decodeMap[dicodeCompress(c1, c2)] = c1 + c2
        self.encodeMap[c1 + c2] = dicodeCompress(c1, c2)

    # Reference: https://www.codegrepper.com/code-examples/python/UnicodeDecodeError%3A+%27utf-8%27+codec+can%27t+decode+byte+0x91+in+position+14%3A+invalid+start+byte
    content = fp.read().decode('ISO-8859-1')
    return content.split('\n')

  def encodeSymbol(self, symbol):
    if len(symbol) < 2:
      return symbol

    encodedSymbol = ''
    i = 0
    while i + 1 < len(symbol):
      curCode = symbol[i:i + 2]
      if curCode in self.encodeMap:
        encodedSymbol += self.encodeMap[curCode]
        i += 2
      else:
        encodedSymbol += symbol[i]
        i += 1

    if i < len(symbol):
      encodedSymbol += symbol[-1]

    return encodedSymbol

  def decodeSymbol(self, symbol):
    for code in self.decodeMap:
      symbol = symbol.replace(code, self.decodeMap[code])

    return symbol

  def loadCscopeDB(self):
    self.log('Loading cscope.out...')

    with open('cscope.out', 'rb') as fp:
      cscope = self.loadCscopeContent(fp)

    '''
    format: {
      symbol: {
        file_path: [line_number,...],
        ...
      }
    }
    '''
    self.definitions = {}
    self.macroDefinitions = {}
    self.macroEnds = {}
    self.functionDefinitions = {}
    self.functionEnds = {}
    self.symbolDefinitions = {}
    self.references = {}
    self.parseRef(cscope)

  def addRef(self, filePath, lineNumber, symbol):
    if symbol not in self.references:
      self.references[symbol] = {}

    if filePath not in self.references[symbol]:
      self.references[symbol][filePath] = []

    self.references[symbol][filePath].append(lineNumber)

  def addDef(self, filePath, lineNumber, symbol):
    if symbol not in self.definitions:
      self.definitions[symbol] = {}

    if filePath not in self.definitions[symbol]:
      self.definitions[symbol][filePath] = []

    self.definitions[symbol][filePath].append(lineNumber)

  def addFuncDef(self, filePath, lineNumber, symbol):
    if symbol not in self.functionDefinitions:
      self.functionDefinitions[symbol] = {}

    if filePath not in self.functionDefinitions[symbol]:
      self.functionDefinitions[symbol][filePath] = []

    self.functionDefinitions[symbol][filePath].append(lineNumber)

  def addFuncEnd(self, filePath, lineNumber, symbol):
    if symbol not in self.functionEnds:
      self.functionEnds[symbol] = {}

    if filePath not in self.functionEnds[symbol]:
      self.functionEnds[symbol][filePath] = []

    self.functionEnds[symbol][filePath].append(lineNumber)

  def addSymbolDef(self, filePath, lineNumber, symbol):
    if symbol not in self.symbolDefinitions:
      self.symbolDefinitions[symbol] = {}

    if filePath not in self.symbolDefinitions[symbol]:
      self.symbolDefinitions[symbol][filePath] = []

    self.symbolDefinitions[symbol][filePath].append(lineNumber)

  def addMacroDef(self, filePath, lineNumber, symbol):
    if symbol not in self.macroDefinitions:
      self.macroDefinitions[symbol] = {}

    if filePath not in self.macroDefinitions[symbol]:
      self.macroDefinitions[symbol][filePath] = []

    self.macroDefinitions[symbol][filePath].append(lineNumber)

  def addMacroEnd(self, filePath, lineNumber, symbol):
    if symbol not in self.macroEnds:
      self.macroEnds[symbol] = {}

    if filePath not in self.macroEnds[symbol]:
      self.macroEnds[symbol][filePath] = []

    self.macroEnds[symbol][filePath].append(lineNumber)

  def encodeFileLineSymbol(self, fileName, lineNumber, symbol):
    return "%s,%s,%s" % (fileName, lineNumber, symbol)

  def decodeFileLineSymbol(self, fileLineSymbol):
    splitted = fileLineSymbol.split(',')
    if len(splitted) < 3:
      return [STR_DEFAULT_FILENAME, 0, 'None']
    [fileName, lineNumber, symbol] = splitted
    return [fileName, int(lineNumber), symbol]

  def parseRef(self, cscope):
    self.log('Parsing cscope.out ...')

    ENUM_NORMAL = 0
    ENUM_EMPTY = 1
    ENUM_DEFINE = 2

    state = ENUM_NORMAL
    curFileName = STR_DEFAULT_FILENAME
    curLineNum = 0
    curFunctionName = STR_DEFAULT_FUNCTION
    curMacroName = STR_DEFAULT_MACRO

    for line in cscope:
      # Less frequently option, lower priority
      # Find empty space
      if state != ENUM_DEFINE and line == '':
        state = ENUM_EMPTY
        continue

      if line == '' or line[0] == ' ':
        continue

      # Find line number
      if state == ENUM_EMPTY and line[0].isnumeric():
        curLineNum = int(line.split(' ')[0])
        state = ENUM_NORMAL
        continue

      if line[0] == '\t':
        lineHead = line[1]
        lineEnd = line[2:]

        # Find reference
        if lineHead == STR_REFERENCE_HEAD:
          self.addRef(curFileName, curLineNum, lineEnd)
          continue

        # Find define macro
        if state != ENUM_DEFINE and lineHead == STR_DEFINE_HEAD:
          state = ENUM_DEFINE
          self.addDef(curFileName, curLineNum, lineEnd)
          self.addMacroDef(curFileName, curLineNum, lineEnd)
          curMacroName = self.encodeFileLineSymbol(curFileName, curLineNum, lineEnd)
          continue

        # End of define macro
        if state == ENUM_DEFINE and lineHead == STR_DEFINE_END_HEAD:
          state = ENUM_NORMAL
          self.addMacroEnd(curFileName, curLineNum, curMacroName)
          curMacroName = STR_DEFAULT_MACRO
          continue

        # Find definition
        if lineHead == STR_DEFINITION_HEAD:
          self.addDef(curFileName, curLineNum, lineEnd)
          self.addFuncDef(curFileName, curLineNum, lineEnd)
          curFunctionName = self.encodeFileLineSymbol(curFileName, curLineNum, lineEnd)
          continue

        # End of function
        if lineHead == STR_FUNCTION_END_HEAD:
          self.addFuncEnd(curFileName, curLineNum, curFunctionName)
          curFunctionName = STR_DEFAULT_FUNCTION
          continue

        # Find class definition, struct, typedef, enum, or enum value
        if (lineHead == STR_CLASS_DEFINITION_HEAD or
            lineHead == STR_STRUCT_HEAD or
            lineHead == STR_TYPEDEF_HEAD or
            lineHead == STR_ENUM_HEAD or
            lineHead == STR_MARK_HEAD):
          self.addDef(curFileName, curLineNum, lineEnd)
          self.addSymbolDef(curFileName, curLineNum, lineEnd)
          continue

        # Find filename
        if lineHead == STR_FILENAME_HEAD:
          curFileName = lineEnd
          curLineNum = 1
          continue

      # Find reference in define macro
      if RE_ISWORD.match(line[0]):
        self.addRef(curFileName, curLineNum, line)
        continue

  def buildDefinitionMap(self):
    '''
    Target: used for finding caller
    Output: {
      file_path: {
        line_number: [symbol1, symbol2...]
      }
    }
    '''
    self.log('Build definition map ...')

    def _buildDefinitionMap(definitions):
      '''
      Input format: {
        symbol: {
          file_path: [line_number,...],
          ...
        }
      }
      '''
      result = {}

      for symbol in definitions:
        info = definitions[symbol]
        for file_path in info:
          for line_number in info[file_path]:
            if file_path not in result:
              result[file_path] = {}

            if line_number not in result[file_path]:
              result[file_path][line_number] = []

            result[file_path][line_number].append(symbol)

      return result

    self.definitionMap = _buildDefinitionMap(self.definitions)
    self.functionDefinitionMap = _buildDefinitionMap(self.functionDefinitions)
    self.functionEndMap = _buildDefinitionMap(self.functionEnds)
    self.macroDefinitionMap = _buildDefinitionMap(self.macroDefinitions)
    self.macroEndMap = _buildDefinitionMap(self.macroEnds)

  def matchBlackList(self, symbol):
    for blackListItem in LIST_BLACKLIST:
      if re.match(blackListItem, symbol):
        self.log('Match blackList! Symbol:', symbol, 'Pattern:', blackListItem)
        return True

    return False

  def toFileLine(self, filePath, lineNumber):
    return "File: %s, Line %d" % (filePath, lineNumber)

  def findCaller(self, filePath, lineNumber, symbol):
    ENUM_GREATER_OR_EQUAL = 0
    ENUM_LESS_OR_EQUAL = 1

    # Binary search
    def binarySearch(lineNumbers, mode):
      callerLine = 0
      left = 0
      right = len(lineNumbers) - 1

      while left <= right:
        middle = (left + right) // 2
        if lineNumbers[middle] == lineNumber:
          callerLine = lineNumbers[middle]
          break
        elif lineNumbers[middle] > lineNumber:
          right = middle - 1
        else:
          left = middle + 1

      if callerLine == 0:
        if mode == ENUM_LESS_OR_EQUAL:
          while middle + 1 < len(lineNumbers) and lineNumbers[middle] < lineNumber:
            middle += 1
          while middle > 0 and lineNumbers[middle] >= lineNumber:
            middle -= 1
        elif mode == ENUM_GREATER_OR_EQUAL:
          while middle > 0 and lineNumbers[middle] >= lineNumber:
            middle -= 1
          while middle + 1 < len(lineNumbers) and lineNumbers[middle] < lineNumber:
            middle += 1
        else:
          print('Invalid mode %d !' % mode)
          return -1

      return middle

    # Find macro define position
    if filePath in self.macroEndMap:
      lineNumbers = [int(num) for num in self.macroEndMap[filePath]]
      macroEndIndex = binarySearch(lineNumbers, ENUM_GREATER_OR_EQUAL)
      if macroEndIndex > -1:
        result = []
        macroEndLineNumber = lineNumbers[macroEndIndex]
        macroInfos = self.macroEndMap[filePath][macroEndLineNumber]
        for macroInfo in macroInfos:
          _, macroLineNumber, symbol = self.decodeFileLineSymbol(macroInfo)
          if macroLineNumber <= lineNumber and macroEndLineNumber >= lineNumber:
            result.append(symbol)

        if len(result) > 0:
          return result

    # If not a macro define, find function definition position
    if filePath in self.functionEndMap:
      lineNumbers = [int(num) for num in self.functionEndMap[filePath]]
      functionEndIndex = binarySearch(lineNumbers, ENUM_GREATER_OR_EQUAL)
      if functionEndIndex > -1:
        result = []
        functionEndLineNumber = lineNumbers[functionEndIndex]
        macroInfos = self.functionEndMap[filePath][functionEndLineNumber]
        for macroInfo in macroInfos:
          _, functionLineNumber, symbol = self.decodeFileLineSymbol(macroInfo)
          if functionLineNumber <= lineNumber and functionEndLineNumber >= lineNumber:
            result.append(symbol)

        if len(result) > 0:
          return result

    # Search nothing
    return None

  def findAllCaller(self, symbol, depth):
    if NUM_MAX_DEPTH != -1 and depth >= NUM_MAX_DEPTH:
      return STR_MAX_DEPTH

    if self.matchBlackList(symbol):
      return STR_BLACKLISTED

    if symbol in self.traversed:
      return STR_TRAVERSED

    if symbol not in self.references:
      return STR_NO_REFERENCE

    callerDict = {}
    callerList = []
    refPosition = {}

    references = self.references[symbol]
    for filePath in references:
      refLines = references[filePath]
      for lineNumber in refLines:
        caller = self.findCaller(filePath, lineNumber, symbol)
        if caller == None:
          continue
        for _caller in caller:
          refPosition[_caller] = (filePath, lineNumber)
        callerList += caller

    callerList = list(set(callerList))
    self.traversed[symbol] = callerList

    for caller in callerList:
      decodedCaller = self.decodeSymbol(caller)
      if caller in self.traversed:
        if caller not in callerDict:
          if BOOL_SHOW_POSITION:
            callerDict[decodedCaller] = {
              'callee': self.toFileLine(refPosition[caller][0], refPosition[caller][1]),
              'caller': STR_TRAVERSED
            }
          else:
            callerDict[decodedCaller] = STR_TRAVERSED
      else:
        if BOOL_SHOW_POSITION:
          callerDict[decodedCaller] = {
            'callee': self.toFileLine(refPosition[caller][0], refPosition[caller][1]),
            'caller': self.findAllCaller(caller, depth + 1)
          }
        else:
          callerDict[decodedCaller] = self.findAllCaller(caller, depth + 1)

    if len(callerDict) == 0:
      return STR_NO_REFERENCE

    return callerDict

  def buildTree(self):
    self.log('Build call tree ...')

    self.trees = {}
    for symbol in self.symbols:
      self.trees[symbol] = self.findAllCaller(self.encodeSymbol(symbol), 0)

  def toString(self):
    spaces = ['']

    def toStr(node, nodeName, depth):
      result = '%s %s\n' % (spaces[depth], nodeName)
      depth1 = depth + 1
      if depth1 == len(spaces):
        if depth1 > 50:
          spaces.append('%d' % depth1)
        else:
          spaces.append('  ' * depth1)

      if type(node) == str:
        return result + '%s %s\n' % (spaces[depth1], node)

      for functionName in node:
        result += toStr(node[functionName], functionName, depth1)

      return result

    result = ''
    for symbol in self.trees:
      result += toStr(self.trees[symbol], symbol, 0)
    return result

  def toJsList(self):
    result = '{'

    def flatten(node):
      nonlocal result

      for callee in node:
        if type(node[callee]) == str:
          result += '"%s":"%s",' % (callee, node[callee])
        else:
          result += '"%s":{' % callee
          flatten(node[callee])
          result += '},'

    for symbol in self.trees:
      result += '"%s":{' % symbol
      flatten(self.trees[symbol])
      result += '},'

    result += '}'
    return result

  def toHtml(self):
    htmlHead = '''
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CallTree</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-1BmE4kWBq78iYhFldvKuhfTAU6auU8tT94WrHftjDbrCEXSU1oBoqyl2QvZ6jIW3" crossorigin="anonymous">
  <script>
    var callTree = %s;
    var callMap = {};

    function toggleChild(e) {
      e.stopPropagation();
      let nextElement = e.target.nextSibling;
      if (!nextElement) return;

      if (nextElement.classList.contains('hide')) {
        console.log('hide -> no hide');
      } else {
        console.log('no hide -> hide');
      }
      nextElement.classList.toggle('hide');
    }

    function buildCallMap(node) {
      if (typeof(node) === 'string') return;

      for (var caller in node) {
        console.assert(
          node[caller] === '@Traversed' ||
            node[caller] === '@NoReference' ||
            callMap[caller] === undefined,
          `${caller} should not in callMap!! Old:`, callMap[caller], 'new: ', node[caller]
        );
        callMap[caller] = node[caller];
        buildCallMap(node[caller])
      }
    };

    function drawMap(node, nodeName) {
      let element = document.createElement('div');
      let text = document.createElement('div');
      let childWrapper = document.createElement('div');
      text.innerText = nodeName;
      text.onclick = toggleChild;
      text.classList.add('node-button')

      element.className = 'node';
      element.appendChild(text);

      if (node === '@Traversed' || node === '@NoReference') {
        let traversedElement = document.createElement('div')
        traversedElement.innerText = node;
        traversedElement.classList.add('node');
        if (node === '@NoReference') {
          traversedElement.classList.add('cursor-not-allowed');
        }
        childWrapper.appendChild(traversedElement);
      } else {
        for (let callee in node) {
          childWrapper.appendChild(drawMap(node[callee], callee));
        }
      }
      element.appendChild(childWrapper);

      return element;
    }

    window.onload = function() {
      let rootEle = document.getElementById('root');
      let container = document.createElement('div')
      container.classList.add('container');
      buildCallMap(callTree);
      for (let caller in callTree) {
        container.appendChild(drawMap(callTree[caller], caller));
      }
      rootEle.appendChild(container);
    }
  </script>
  <style>
    .node {
      padding-left: 1rem;
      border-left: 1px dotted gray;
    }
    .node-button {
      cursor: pointer;
      transition: 0.15s;
      padding: 0rem 1rem;
      position: relative;
      left: -1rem;
      border-radius: 0.2rem;
    }
    .node-button:hover {
      background-color: rgba(0, 0, 0, 0.1);
    }
    .hide {
      display: none;
    }
    .cursor-not-allowed {
      cursor: not-allowed;
    }
    .no-selection {
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      -khtml-user-select: none;
      -moz-user-select: none;
      -ms-user-select: none;
      user-select: none;
    }
  </style>
</head>
''' % self.toJsList()

    htmlBegin = '''
<!DOCTYPE html>
<html lang="en">
'''

    htmlBody = '''
  <body>
    <noscript>You need to enable JavaScript to run this app.</noscript>
    <div id="root"></div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-ka7Sk0Gln4gmtz2MlQnikT1wXgYsOg+OMhuP+IlRH9sENBO0LRn5q+8nbTov4+1p" crossorigin="anonymous"></script>
  </body>
'''

    htmlEnd = '</html>'

    return htmlBegin + htmlHead + htmlBody + htmlEnd

os.chdir(args.path)

ct = CallTree(args.symbols.split(','))
treeStr = ct.toHtml()

if not BOOL_BACKGROUND:
  print(treeStr)

with open(args.output, 'w') as fp:
  fp.write(treeStr)
