#!/usr/bin/env python3

import argparse
import sqlite3
import os
import sys
import re
import json

parser = argparse.ArgumentParser()
parser.add_argument('symbols', type=str, help='The root symbols of caller tree. If you want to build multiple trees at a time, use comma without space to seperate each symbol. For example, `symbol1,symbol2`')
parser.add_argument('--path', type=str, default='.', help='Path to the GPATH/GRTAGS/GTAGS with sqlite3 format.')
parser.add_argument('--blacklist', type=str, default='', help='List of black list. Use comma to seperate each symbol with space. For example, `DEBUG,RANDOM`')
parser.add_argument('-v', '--verbose', action='store_true', help='Show more log for debugging.')
parser.add_argument('--show_position', action='store_true', help='Whether to show ref file and line number.')
args = parser.parse_args()

BOOL_VERBOSE = args.verbose
BOOL_SHOW_POSITION = args.show_position

STR_TRAVERSED = '@Traversed'
STR_BLACKLISTED = '@Blacklisted'

LIST_BLACKLIST = args.blacklist.split(',')

class CallTree:
  def __init__(self, symbols):
    # We should find three files (GTAGS, GRTAGS, and GPATH) under current directory.
    findAllFile = True

    if not os.path.exists('GTAGS'):
      print('Cannot find GTAGS')
      findAllFile = False
    if not os.path.exists('GRTAGS'):
      print('Cannot find GRTAGS')
      findAllFile = False
    if not os.path.exists('GPATH'):
      print('Cannot find GPATH')
      findAllFile = False

    if not findAllFile:
      sys.exit(1)

    # Load symbols from SQLITE3 data base
    self.traversed = {}
    self.symbols = symbols
    self.checkedMacro = {}
    self.definitions = {}
    self.references = {}
    self.pathMap = {}
    self.functionDefinitions = {}

    self.loadGtags('GTAGS') # format: {symbol: [file_symbol symbol line_number original_code, file_symbol]}
    self.loadRtags('GRTAGS') # format: {symbol: [file_symbol symbol line_number,line_number..., file_symbol]}
    self.loadPath('GPATH')      # format: {file_symbol/path: path/file_symbol}
    self.buildTree()

  def loadDB(self, filename):
    con = sqlite3.connect(filename)
    cursor = con.cursor()
    cursor.execute('Select * from db;')
    return cursor.fetchall()

  def loadRtags(self, filename):
    allData = self.loadDB(filename)

    result = {}
    for item in allData:
      if item[0] in result:
        result[item[0]].append(item[1:])
      else:
        result[item[0]] = [item[1:]]

    self.references = result

  def loadGtags(self, filename):
    allData = self.loadDB(filename)

    result = {}
    functionResult = {}
    for item in allData:
      if item[0] in result:
        result[item[0]].append(item[1:])
      else:
        result[item[0]] = [item[1:]]

      sourceCode = item[1].split(' ', 3)
      if len(sourceCode) <= 3:
        continue
      else:
        sourceCode = sourceCode[3]

      if self.isSourceCodeDefineMacro(sourceCode):
        continue

      if item[0] in functionResult:
        functionResult[item[0]].append(item[1:])
      else:
        functionResult[item[0]] = [item[1:]]

    self.definitions = result
    self.functionDefinitions = functionResult

  def loadPath(self, filename):
    allData = self.loadDB(filename)

    result = {}
    for item in allData:
      if item[0] in result:
        if BOOL_VERBOSE:
          print('Repeated item!!!', item)
      result[item[0]] = item[1]

    self.pathMap = result

  def buildDefinitionMap(self):
    '''
    Target: used for finding caller
    Output: {
      file_symbol: {
        line_number: [symbol1, symbol2...]
      }
    }
    '''
    result = {}

    for symbol in self.definitions:
      symbolInfos = self.definitions[symbol]
      for symbolInfo in symbolInfos:
        fileSymbol = symbolInfo[1]
        symbolInfoList = symbolInfo[0].split(' ')
        if len(symbolInfoList) < 3:
          continue
        lineNumber = symbolInfoList[2]
        if not lineNumber.isnumeric():
          continue

        if fileSymbol not in result:
          result[fileSymbol] = {}

        if lineNumber in result[fileSymbol]:
          result[fileSymbol][lineNumber].append(symbol)
        else:
          result[fileSymbol][lineNumber] = [symbol]

    self.definitionMap = result

    result = {}

    for symbol in self.functionDefinitions:
      symbolInfos = self.functionDefinitions[symbol]
      for symbolInfo in symbolInfos:
        fileSymbol = symbolInfo[1]
        symbolInfoList = symbolInfo[0].split(' ')
        if len(symbolInfoList) < 3:
          continue
        lineNumber = symbolInfoList[2]
        if not lineNumber.isnumeric():
          continue

        if fileSymbol not in result:
          result[fileSymbol] = {}

        if lineNumber in result[fileSymbol]:
          result[fileSymbol][lineNumber].append(symbol)
        else:
          result[fileSymbol][lineNumber] = [symbol]

    self.functionDefinitionMap = result

  def splitLineNumbers(self, lineNumbers):
    '''
    Input: 'number1,number2-number3,...'
    Output: [
      lineNumber1,
      lineNumber2,
      ...
    ]
    '''
    lineNumberList = []
    curNumber = 0

    lineNumbers = lineNumbers.split(',')
    for num in lineNumbers:
      if '-' not in num:
        assert(num.isnumeric())
        curNumber += int(num)
        lineNumberList.append(curNumber)
      else:
        [num, repeats] = num.split('-')
        assert(num.isnumeric())
        assert(repeats.isnumeric())

        curNumber += int(num)
        for i in range(int(repeats) + 1):
          lineNumberList.append(curNumber + i)
        curNumber += int(repeats)

    return lineNumberList

  def checkIsCalleeInCallerMacro(self, fileSymbol, lineNumber, callerLineNumber):
    if lineNumber < 2:
      return False

    filePath = self.pathMap[fileSymbol]
    assert(os.path.exists(filePath))

    with open(self.pathMap[fileSymbol]) as fp:
      codes = fp.readlines()

    callerLineNumber -= 1
    while True:
      line = codes[callerLineNumber].strip()
      if callerLineNumber == lineNumber - 1:
        return True
      if line[-1] == '\\':
        callerLineNumber += 1
        continue

      return False

  def isSourceCodeDefineMacro(self, string):
    return re.match(r'#\s*@d\s+@n', string)

  def checkIsCallerMacro(self, symbols):
    result = False

    for symbol in symbols:
      if symbol in self.checkedMacro:
        result = result or self.checkedMacro[symbol]

      if result:
        return True

      if symbol not in self.definitions:
        self.checkedMacro[symbol] = False
        return False

      for defInfo in self.definitions[symbol]:
        originalCode = defInfo[0].split(' ', 3)[3]
        if self.isSourceCodeDefineMacro(originalCode):
          self.checkedMacro[symbol] = True
          return True

      self.checkedMacro[symbol] = False

    return False

  def findCaller(self, fileSymbol, lineNumber):
    if fileSymbol not in self.definitionMap:
      if BOOL_VERBOSE:
        print('Cannot find file symbol', fileSymbol)
      return None

    # Use binary search to find the caller
    def searchEngine(lineNumbers):
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
        while middle < len(lineNumbers) and lineNumbers[middle] < lineNumber:
          middle += 1
        middle = min(len(lineNumbers) - 1, middle)
        while middle > 0 and lineNumbers[middle] >= lineNumber:
          middle -= 1

      return middle

    # Search with all definitions
    definitions = self.definitionMap[fileSymbol]
    lineNumbers = [int(num) for num in definitions.keys()]
    lineNumbers = sorted(lineNumbers)

    middle = searchEngine(lineNumbers)

    callerLine = lineNumbers[middle]

    if middle == -1:
      return None
    else:
      callerLine = lineNumbers[middle]

    possibleCallerSymbol = self.definitionMap[fileSymbol][str(callerLine)]

    if self.checkIsCallerMacro(possibleCallerSymbol) and self.checkIsCalleeInCallerMacro(fileSymbol, lineNumber, callerLine):
      return possibleCallerSymbol

    # Search again with function only definition
    if fileSymbol not in self.functionDefinitionMap:
      if BOOL_VERBOSE:
        print('Cannot find file symbol', fileSymbol)
      return None

    definitions = self.functionDefinitionMap[fileSymbol]
    lineNumbers = [int(num) for num in definitions.keys()]
    lineNumbers = sorted(lineNumbers)

    middle = searchEngine(lineNumbers)

    callerLine = lineNumbers[middle]

    if middle == -1:
      return None
    else:
      callerLine = lineNumbers[middle]

    possibleCallerSymbol = self.definitionMap[fileSymbol][str(callerLine)]

    return possibleCallerSymbol

  def toFileLine(self, fileSymbol, lineNumber):
    return "File: %s, Line %d" % (self.pathMap[fileSymbol], lineNumber)

  def findAllCaller(self, symbol):
    if symbol in LIST_BLACKLIST:
      return STR_BLACKLISTED

    if symbol in self.traversed:
      return STR_TRAVERSED

    if symbol not in self.references:
      return {}

    callerDict = {}
    callerList = []
    refPosition = {}

    references = self.references[symbol]
    for ref in references:
      fileSymbol = ref[1]

      ref = ref[0].split(' ')
      if len(ref) < 3:
        if BOOL_VERBOSE:
          print('Error! Length of ref is less than 3! Ref:', ref)
        continue
      lineNumbers = ref[2]
      lineNumbers = self.splitLineNumbers(lineNumbers)
      for lineNumber in lineNumbers:
        caller = self.findCaller(fileSymbol, lineNumber)
        # Check whether this symbol has been traversed
        if caller == None:
          continue
        for _caller in caller:
          refPosition[_caller] = (fileSymbol, lineNumber)
        callerList += caller

    self.traversed[symbol] = list(set(callerList))

    for caller in callerList:
      if caller in self.traversed:
        if caller not in callerDict:
          if BOOL_SHOW_POSITION:
            callerDict[caller] = {
              'position': self.toFileLine(refPosition[caller][0], refPosition[caller][1]),
              'caller': STR_TRAVERSED
            }
          else:
            callerDict[caller] = STR_TRAVERSED
      else:
        if BOOL_SHOW_POSITION:
          callerDict[caller] = {
            'position': self.toFileLine(refPosition[caller][0], refPosition[caller][1]),
            'caller': self.findAllCaller(caller)
          }
        else:
          callerDict[caller] = self.findAllCaller(caller)

    return callerDict

  def buildTree(self):
    self.trees = {}

    self.buildDefinitionMap()

    # For test only
    for symbol in self.symbols:
      self.trees[symbol] = self.findAllCaller(symbol)

os.chdir(args.path)
ct = CallTree(args.symbols.split(','))
print(json.dumps(ct.trees, indent = 2))