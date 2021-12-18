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
parser.add_argument('-o', '--output', type=str, default='calltree.txt', help='The output file name.')
parser.add_argument('-d', '--depth', type=int, default=999, help='Max depth of result. Default is 999, which is also maximal value.')
parser.add_argument('-t', '--tag_version', type=str, default='cscope', choices=['global', 'cscope'], help='Choose tag system you want to use. Available choices: [global(tags generated with sqlite3 support), cscope] Default: cscope.')
parser.add_argument('-v', '--verbose', action='store_true', help='Show more log for debugging.')
parser.add_argument('-s', '--show_position', action='store_true', help='Whether to show ref file and line number.')
parser.add_argument('-g', '--background', action='store_true', help='Whether NOT to print output to stdout.')
args = parser.parse_args()

BOOL_VERBOSE              = args.verbose
BOOL_SHOW_POSITION        = args.show_position
BOOL_BACKGROUND           = args.background

NUM_MAX_DEPTH             = max(min(args.depth, 999), 1)

STR_TRAVERSED             = '@Traversed'
STR_BLACKLISTED           = '@Blacklisted'
STR_MAX_DEPTH             = '@ReachMaxDepth'
STR_NO_REFERENCE          = '@NoReference'
STR_TAG_VERSION           = args.tag_version
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

class CallTree_Cscope:
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
        macroEndLineNumber = lineNumbers[macroEndIndex]
        [macroInfo] = self.macroEndMap[filePath][macroEndLineNumber]
        _, macroLineNumber, symbol = self.decodeFileLineSymbol(macroInfo)
        if macroLineNumber <= lineNumber and macroEndLineNumber >= lineNumber:
          return [symbol]

    # If not a macro define, find function definition position
    if filePath in self.functionEndMap:
      lineNumbers = [int(num) for num in self.functionEndMap[filePath]]
      functionEndIndex = binarySearch(lineNumbers, ENUM_GREATER_OR_EQUAL)
      if functionEndIndex > -1:
        functionEndLineNumber = lineNumbers[functionEndIndex]
        [macroInfo] = self.functionEndMap[filePath][functionEndLineNumber]
        _, functionLineNumber, symbol = self.decodeFileLineSymbol(macroInfo)
        if functionLineNumber <= lineNumber and functionEndLineNumber >= lineNumber:
          return [symbol]

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

class CallTree_Global:
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

    self.loadGtags('GTAGS')  # format: {symbol: [file_symbol symbol line_number original_code, file_symbol]}
    self.loadRtags('GRTAGS') # format: {symbol: [file_symbol symbol line_number,line_number..., file_symbol]}
    self.loadPath('GPATH')   # format: {file_symbol/path: path/file_symbol}
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

    if BOOL_VERBOSE:
      print('Read', self.pathMap[fileSymbol])

    try:
      with open(self.pathMap[fileSymbol]) as fp:
        codes = fp.readlines()
    except:
      print('Fail to read file', self.pathMap[fileSymbol])
      return False

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
        splittedDefInfo = defInfo[0].split(' ', 3)
        if len(splittedDefInfo) < 4:
          continue
        originalCode = splittedDefInfo[3]
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

  def matchBlackList(self, symbol):
    for blackListItem in LIST_BLACKLIST:
      if re.match(blackListItem, symbol):
        return True

    return False

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
              'callee': self.toFileLine(refPosition[caller][0], refPosition[caller][1]),
              'caller': STR_TRAVERSED
            }
          else:
            callerDict[caller] = STR_TRAVERSED
      else:
        if BOOL_SHOW_POSITION:
          callerDict[caller] = {
            'callee': self.toFileLine(refPosition[caller][0], refPosition[caller][1]),
            'caller': self.findAllCaller(caller, depth + 1)
          }
        else:
          callerDict[caller] = self.findAllCaller(caller, depth + 1)

    return callerDict

  def buildTree(self):
    self.trees = {}

    self.buildDefinitionMap()

    # For test only
    for symbol in self.symbols:
      self.trees[symbol] = self.findAllCaller(symbol, 0)

os.chdir(args.path)

if STR_TAG_VERSION == 'global':
  ct = CallTree_Global(args.symbols.split(','))
elif STR_TAG_VERSION == 'cscope':
  ct = CallTree_Cscope(args.symbols.split(','))

treeStr = json.dumps(ct.trees, indent = 2)

if not BOOL_BACKGROUND:
  print(treeStr)

with open(args.output, 'w') as fp:
  fp.write(treeStr)
