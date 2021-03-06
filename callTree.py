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
parser.add_argument('-d', '--depth', type=int, default=50, help='Max depth of result. Default is 50, maximal value is 900.')
parser.add_argument('-v', '--verbose', action='store_true', help='Show more log for debugging.')
parser.add_argument('-n', '--no_position', action='store_false', help='Whether NOT to show ref file and line number.')
parser.add_argument('-g', '--background', action='store_true', help='Whether NOT to print output to stdout.')
args = parser.parse_args()

BOOL_VERBOSE              = args.verbose
BOOL_NO_POSITION        = args.no_position
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
    self.log('Loading cscope.out ...')

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
    if len(LIST_BLACKLIST) == 0:
      return False
    
    decodedSymbol = self.decodeSymbol(symbol)

    for blackListItem in LIST_BLACKLIST:
      if re.match(blackListItem, decodedSymbol):
        self.log('Match blackList! Symbol:', decodedSymbol, 'Pattern:', blackListItem)
        return True

    return False

  def toFileLine(self, filePath, lineNumber):
    # return "File: %s, Line %d" % (filePath, lineNumber)
    return "%s,%d" % (filePath, lineNumber)

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
          if BOOL_NO_POSITION:
            callerDict[decodedCaller] = {
              'callee': self.toFileLine(refPosition[caller][0], refPosition[caller][1]),
              'caller': STR_TRAVERSED
            }
          else:
            callerDict[decodedCaller] = STR_TRAVERSED
      else:
        if BOOL_NO_POSITION:
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
      if type(self.trees[symbol]) == str:
        result += '"%s":"%s",' % (symbol, self.trees[symbol])
      else:
        result += '"%s":{' % symbol
        flatten(self.trees[symbol])
        result += '},'

    result += '}'
    return result

  def toHtml(self):
    self.log('Convert tree to HTML ...')
    htmlContent = '''
<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CallTree</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-1BmE4kWBq78iYhFldvKuhfTAU6auU8tT94WrHftjDbrCEXSU1oBoqyl2QvZ6jIW3" crossorigin="anonymous">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
  <script>
    var showPosition = %s;
    var callTree = %s;

    function getArrowDown() {
      let ele = document.createElement('i');
      ele.classList.add('fa');
      ele.classList.add('fa-angle-down');
      return ele;
    };

    function getArrowRight() {
      let ele = document.createElement('i');
      ele.classList.add('fa');
      ele.classList.add('fa-angle-right');
      return ele;
    };

    function getCopy() {
      let ele = document.createElement('i');
      ele.classList.add('fa');
      ele.classList.add('fa-copy');
      return ele;
    }

    function getLink() {
      let ele = document.createElement('i');
      ele.classList.add('fa');
      ele.classList.add('fa-link');
      return ele;
    }

    function toggleTextSelection() {
      let root = document.getElementById('root');
      root.classList.toggle('no-selection');
    }

    function toggleChild(e) {
      e.stopPropagation();
      let innerText = null;
      let nextElement = null;
      let target = null;
      if (e.target.classList && e.target.classList.contains('fa')) {
        innerText = e.target.nextSibling.textContent;
        nextElement = e.target.parentNode.nextSibling;
        target = e.target.parentNode;
      } else {
        innerText = e.target.innerText;
        nextElement = e.target.nextSibling;
        target = e.target;
      }

      if (!nextElement || !nextElement.classList) return;

      if (nextElement.classList.contains('hide')) {
        target.children[0].classList.remove('fa-angle-right');
        target.children[0].classList.add('fa-angle-down');
      } else {
        target.children[0].classList.remove('fa-angle-down');
        target.children[0].classList.add('fa-angle-right');
      }

      nextElement.classList.toggle('hide');
    }

    function collapseAll() {
      let elements = null;

      elements = document.getElementsByClassName('node');
      for (let i = 0; i < elements.length; i++) {
        let element = elements[i];
        if (element.children.length < 2) continue;
        element.children[1].classList.add('hide');
      }

      elements = document.getElementsByClassName('node-button');
      for (let i = 0; i < elements.length; i++) {
        let element = elements[i];
        let classList = element.children[0].classList;
        if (classList.contains('fa-angle-down')) {
          classList.remove('fa-angle-down');
          classList.add('fa-angle-right');
        }
      }

      window.scrollTo(0, 0);
    }

    function expandAll() {
      let elements = null;

      elements = document.getElementsByClassName('node');
      for (let i = 0; i < elements.length; i++) {
        let element = elements[i];
        if (element.children.length < 2) continue;
        let classList = element.children[1].classList;
        if (classList.contains('hide')) classList.remove('hide');
      }

      elements = document.getElementsByClassName('node-button');
      for (let i = 0; i < elements.length; i++) {
        let element = elements[i];
        let classList = element.children[0].classList;
        if (classList.contains('fa-angle-right')) {
          classList.remove('fa-angle-right');
          classList.add('fa-angle-down');
        }
      }
    }

    function autoExpand(element) {
      // Expand all the parent elements
      if (element && element.classList) {
        if (element.classList.contains('hide')) {
          element.classList.remove('hide');
        }

        autoExpand(element.parentNode);
      }
    }

    function drawMap(node, nodeName, calleeInfo='') {
      let element = document.createElement('div');
      let text = document.createElement('div');
      let childWrapper = document.createElement('div');
      let copy = getCopy();

      copy.onclick = copyFunctionName;

      text.appendChild(getArrowDown());
      text.appendChild(document.createTextNode(` ${nodeName} `));
      text.appendChild(copy);
      text.onclick = toggleChild;
      text.classList.add('node-button');

      // Append callee info if available
      if (calleeInfo !== '') {
        calleeInfo = calleeInfo.split(',');

        let filePath = calleeInfo[0];
        let lineNumber = calleeInfo[1];
        let filePathSpan = document.createElement('span');
        let lineNumberSpan = document.createElement('span');
        filePathSpan.classList.add('callerinfo-inner');
        lineNumberSpan.classList.add('callerinfo-inner');
        filePathSpan.innerText = filePath;
        lineNumberSpan.innerText = lineNumber;
        filePathSpan.onclick = copyCallerFile;
        lineNumberSpan.onclick = copyCallerLineNumber;

        let calleeInfoText = document.createElement('span');
        calleeInfoText.appendChild(document.createTextNode('File: '));
        calleeInfoText.appendChild(filePathSpan);
        calleeInfoText.appendChild(document.createTextNode(', Line: '));
        calleeInfoText.appendChild(lineNumberSpan);
        calleeInfoText.classList.add('callerinfo');

        text.appendChild(calleeInfoText);
      }

      element.className = 'node';
      element.appendChild(text);

      if (node === '@Traversed' || node === '@NoReference' || node === '@Blacklisted') {
        let traversedElement = document.createElement('div')
        traversedElement.classList.add('node');
        if (node === '@NoReference' || node === '@Blacklisted') {
          traversedElement.innerText = node;
          traversedElement.classList.add('cursor-not-allowed');
          element.id = nodeName;
        } else {
          let linkElement = document.createElement('a');
          let traversedButton = document.createElement('div');

          traversedButton.classList.add('node-button');
          traversedButton.innerText = node;

          linkElement.href = '#' + nodeName;
          linkElement.appendChild(document.createTextNode(' '));
          linkElement.appendChild(getLink());

          traversedButton.appendChild(linkElement);
          traversedElement.appendChild(traversedButton);
          traversedElement.onclick = () => {
            // Remove selected from all components with class 'selected'
            let selectedElements = document.getElementsByClassName('selected');
            for (let i = 0; i < selectedElements.length; i++) {
              if (!selectedElements[i].classList) continue;
              selectedElements[i].classList.remove('selected');
            }

            // Add style to traversed element
            let targetElement = document.getElementById(nodeName);
            if (!targetElement || !targetElement.children) return;
            targetElement.children[0].classList.add('selected');

            // Auto expand
            autoExpand(targetElement.children[0]);
          };
        }
        childWrapper.appendChild(traversedElement);
      } else {
        element.id = nodeName;
        if (showPosition) {
          for (let callee in node) {
            childWrapper.appendChild(drawMap(node[callee]['caller'], callee, node[callee]['callee']));
          }
        } else {
          for (let callee in node) {
            childWrapper.appendChild(drawMap(node[callee], callee));
          }
        }
      }

      element.appendChild(childWrapper);

      return element;
    }

    function copyFunctionName(e) {
      e.stopPropagation();
      copyToClipboard(e.target.previousSibling.textContent.slice(1,-1), 'function name');
    }

    function copyCallerFile(e) {
      e.stopPropagation();
      copyToClipboard(e.target.innerText, 'caller file info');
    }

    function copyCallerLineNumber(e) {
      e.stopPropagation();
      copyToClipboard(e.target.innerText, 'caller line number info');
    }

    function copyToClipboard(textToCopy, message) {
      if (!navigator) {
        // Show fail toasts
        let failMessageDiv = document.getElementById('copy-fail-message');
        failMessageDiv.innerText = `Copy ${message} failed!`;
        let toast = new bootstrap.Toast(document.getElementById('copy-fail'));
        toast.show();
        return;
      }

      navigator.clipboard.writeText(textToCopy).then(() => {
        // Show success toasts
        let successMessageDiv = document.getElementById('copy-success-message');
        successMessageDiv.innerText = `Copy ${message} successed!`;
        let toast = new bootstrap.Toast(document.getElementById('copy-success'));
        toast.show();
      }).catch(err => {
        // Show fail toasts
        let failMessageDiv = document.getElementById('copy-fail-message');
        failMessageDiv.innerText = `Copy ${message} failed!`;
        let toast = new bootstrap.Toast(document.getElementById('copy-fail'));
        toast.show();
      })
    }

    window.onload = function() {
      let rootEle = document.getElementById('root');
      let paddingBalancer = document.createElement('div');
      paddingBalancer.style.paddingLeft = '1rem';
      for (let caller in callTree) {
        paddingBalancer.appendChild(drawMap(callTree[caller], caller));
      }
      rootEle.appendChild(paddingBalancer);
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
    .clickable {
      cursor: pointer;
      transition: 0.15s;
      padding: 0rem 1rem;
      position: relative;
      border-radius: 0.2rem;
    }
    .node-button:hover, .clickable:hover {
      background-color: rgba(0, 0, 0, 0.1);
    }
    .hide {
      display: none;
    }
    .cursor-not-allowed {
      cursor: not-allowed;
      color: rgba(0, 0, 0, 0.5);
    }
    .no-selection {
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      -khtml-user-select: none;
      -moz-user-select: none;
      -ms-user-select: none;
      user-select: none;
    }
    .fa {
      width: 0.75rem;
    }
    .fa-copy{
      opacity: 0.3;
      transition-duration: 0.15s;
      color: green;
    }
    .fa-link {
      opacity: 0.3;
      transition-duration: 0.15s;
      cursor: pointer;
    }
    .fa-copy:hover, .fa-link:hover {
      opacity: 1;
    }
    .selected{
      background-color: rgba(252, 220, 42, 0.336);
    }
    a {
      text-decoration: none;
    }
    #setting {
      position: fixed;
      right: 1rem;
      top: 1rem;
    }
    .callerinfo {
      margin-left: 1rem;
      color: rgba(0, 0, 0, 0.3);
      cursor: initial;
    }
    .callerinfo-inner {
      transition-duration: 0.15s;
      cursor: pointer;
    }
    .callerinfo-inner:hover {
      color: rgb(53, 117, 255);
    }
  </style>
</head>

  <body>
    <noscript>You need to enable JavaScript to run this app.</noscript>
    <div class="container" style="padding-top: 1rem;">
      <h1>Call Tree</h1>
      <div id="root" class="no-selection"></div>
      <div id="setting">
        <div class="card">
          <div class="card-body">
            <div class="btn-group" role="group" aria-label="Collapse/Expand buttons">
              <button type="button" class="btn btn-outline-primary" onclick="collapseAll()">Collapse All</button>
              <button type="button" class="btn btn-outline-primary" onclick="expandAll()">Expand All</button>
            </div>
          </div>
        </div>
      </div>
      <div style="height: 100vh;"></div>
    </div>
    <div>
      <div class="position-fixed bottom-0 end-0 p-3" style="z-index: 11">
        <div id='copy-success' class="toast align-items-center text-white bg-success border-0" role="alert" aria-live="assertive" aria-atomic="true">
          <div class="d-flex">
            <div id='copy-success-message' class="toast-body">
              success message
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
          </div>
        </div>
      </div>
      <div class="position-fixed bottom-0 end-0 p-3" style="z-index: 11">
        <div id='copy-fail' class="toast align-items-center text-white bg-danger border-0" role="alert" aria-live="assertive" aria-atomic="true">
          <div class="d-flex">
            <div id='copy-fail-message' class="toast-body">
              fail message
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
          </div>
        </div>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-ka7Sk0Gln4gmtz2MlQnikT1wXgYsOg+OMhuP+IlRH9sENBO0LRn5q+8nbTov4+1p" crossorigin="anonymous"></script>
  </body>
</html>
''' % ('true' if BOOL_NO_POSITION else 'false', self.toJsList())

    return htmlContent

os.chdir(args.path)

ct = CallTree(args.symbols.split(','))
treeStr = ct.toHtml()

with open(args.output, 'w') as fp:
  fp.write(treeStr)

ct.log('Done!')
