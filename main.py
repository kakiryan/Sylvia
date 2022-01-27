"""This file is the entrypoint of the execution."""
import pyverilog
import z3
from z3 import Solver, Int, BitVec, Context, BitVecSort, ExprRef, BitVecRef, If, BitVecVal, And
from pyverilog.vparser.parser import parse
from pyverilog.vparser.ast import Description, ModuleDef, Node, IfStatement, SingleStatement, And, Constant, Rvalue, Plus, Input, Output
from pyverilog.vparser.ast import WhileStatement, ForStatement, CaseStatement, Block, SystemCall, Land, InstanceList, IntConst, Partselect, Ioport
from pyverilog.vparser.ast import Value, Reg, Initial, Eq, Identifier, Initial,  NonblockingSubstitution, Decl, Always, Assign, NotEql, Case
from pyverilog.vparser.ast import Concat, BlockingSubstitution, Parameter, StringConst, Wire, PortArg
import sys
import os
from optparse import OptionParser
from typing import Optional
import random, string
import time
from itertools import product
import logging
import gc
from pyverilog.vparser.preprocessor import preprocess
from engine.execution_manager import ExecutionManager
from engine.symbolic_state import SymbolicState
from helpers.rvalue_parser import tokenize, parse_tokens, evaluate
from strategies.dfs import DepthFirst
from engine.execution_engine import ExecutionEngine

gc.collect()

with open('errors.log', 'w'):
    pass
logging.basicConfig(filename='errors.log', level=logging.DEBUG)
logging.debug("Starting over")


INFO = "Verilog Symbolic Execution Engine"
VERSION = pyverilog.__version__
USAGE = "Usage: python3 -m engine <num_cycles> <verilog_file>.v > out.txt"

CONDITIONALS = (IfStatement, ForStatement, WhileStatement, CaseStatement)
EXPRESSIONS = ["Decl"]

def to_binary(i: int, digits: int = 128) -> str:
    num: str = bin(i)[2:]
    padding_len: int = digits - len(num)
    return  ("0" * padding_len) + num 

def parse_expr_to_Z3(e: Value, s: Solver, branch: bool):
    """Takes in a complex Verilog Expression and converts it to 
    a Z3 query."""
    if isinstance(e, And):
        lhs = parse_expr_to_Z3(e.left, s, branch)
        rhs = parse_expr_to_Z3(e.right, s, branch)
        return s.add(lhs.assertions() and rhs.assertions())
    elif isinstance(e, Identifier):
        return BitVec(e.name + "_0", 32)
    elif isinstance(e, Constant):
        return BitVec(int(e.value), 32)
    elif isinstance(e, Eq):
        lhs = parse_expr_to_Z3(e.left, s, branch)
        rhs = parse_expr_to_Z3(e.right, s, branch)
        if branch:
            s.add(lhs == rhs)
        else:
            s.add(lhs != rhs)
        return (lhs == rhs)
    elif isinstance(e, NotEql):
        lhs = parse_expr_to_Z3(e.left, s, branch)
        rhs = parse_expr_to_Z3(e.right, s, branch)
        if branch:          
            # only RHS is BitVec (Lhs is a more complex expr)
            if isinstance(rhs, z3.z3.BitVecRef) and not isinstance(lhs, z3.z3.BitVecRef):
                c = If(lhs, BitVecVal(1, 32), BitVecVal(0, 32))
                s.add(c != rhs)
            else:
                s.add(lhs != rhs)
        else:
            # only RHS is bitVEC 
            if isinstance(rhs, z3.z3.BitVecRef) and not isinstance(lhs, z3.z3.BitVecRef):
                c = If(lhs, BitVecVal(1, 32), BitVecVal(0, 32))
                s.add(c == rhs)
            else:
                s.add(lhs == rhs)
    elif isinstance(e, Land):
        lhs = parse_expr_to_Z3(e.left, s, branch)
        rhs = parse_expr_to_Z3(e.right, s, branch)

        # if lhs and rhs are just simple bit vecs
        if isinstance(rhs, BitVecRef) and isinstance(lhs, BitVecRef):
            #TODO fix this right now im not doing anything
            #s.add(rhs)
            return s
        elif isinstance(rhs, BitVecRef):
            return  s
        elif isinstance(lhs, BitVecRef):
            return  s
        else:
            if lhs is None:
                return s.add(rhs.assertions())
            
            if rhs is None:
                return s.add(rhs.assertions())

            return s.add(lhs.assertions() and rhs.assertions())
    return s

def init_symbol() -> str:
    """Initializes signal with random symbol."""
    #TODO:change symbol length back to 16 or whatever or make this hash to guarantee good randomness
    return ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(16))
    
     
# class ExecutionEngine:
#     branch: bool = True
#     module_depth: int = 0

#     def check_pc_SAT(self, s: Solver, constraint: ExprRef) -> bool:
#         """Check if pc is satisfiable before taking path."""
#         # the push adds a backtracking point if unsat
#         s.push()
#         s.add(constraint)
#         result = s.check()
#         if str(result) == "sat":
#             return True
#         else:
#             s.pop()
#             return False

#     def check_dup(self, m: ExecutionManager) -> bool:
#         """Checks if the current path is a duplicate/worth exploring."""
#         for i in range(len(m.path_code)):
#             if m.path_code[i] == "1" and i in m.completed:
#                 return True
#         return False

#     def solve_pc(self, s: Solver) -> bool:
#         """Solve path condition."""
#         result = str(s.check())
#         if str(result) == "sat":
#             model = s.model()
#             return True
#         else:
#             return False

#     def count_conditionals_2(self, m:ExecutionManager, items) -> int:
#         """Rewrite to actually return an int."""
#         stmts = items
#         if isinstance(items, Block):
#             stmts = items.statements
#             items.cname = "Block"

#         if hasattr(stmts, '__iter__'):
#             for item in stmts:
#                 if isinstance(item, CONDITIONALS):
#                     if isinstance(item, IfStatement) or isinstance(item, CaseStatement):
#                         if isinstance(item, IfStatement):
#                             return self.count_conditionals_2(m, item.true_statement) + self.count_conditionals_2(m, item.false_statement)  + 1
#                         if isinstance(items, CaseStatement):
#                             return self.count_conditionals_2(m, items.caselist) + 1
#                 if isinstance(item, Block):
#                     return self.count_conditionals_2(m, item.items)
#                 elif isinstance(item, Always):
#                    return self.count_conditionals_2(m, item.statement)             
#                 elif isinstance(item, Initial):
#                     return self.count_conditionals_2(m, item.statement)
#         elif items != None:
#             if isinstance(items, IfStatement):
#                 return  ( self.count_conditionals_2(m, items.true_statement) + 
#                 self.count_conditionals_2(m, items.false_statement)) + 1
#             if isinstance(items, CaseStatement):
#                 return self.count_conditionals_2(m, items.caselist) + 1
#         return 0

#     def count_conditionals(self, m: ExecutionManager, items):
#         """Identify control flow structures to count total number of paths."""
#         stmts = items
#         if isinstance(items, Block):
#             stmts = items.statements
#             items.cname = "Block"
#         if hasattr(stmts, '__iter__'):
#             for item in stmts:
#                 if isinstance(item, CONDITIONALS):
#                     if isinstance(item, IfStatement) or isinstance(item, CaseStatement):
#                         if isinstance(item, IfStatement):
#                             m.num_paths *= 2
#                             self.count_conditionals(m, item.true_statement)
#                             self.count_conditionals(m, item.false_statement)
#                         if isinstance(item, CaseStatement):
#                             for case in item.caselist:
#                                 m.num_paths *= 2
#                                 self.count_conditionals(m, case.statement)
#                 if isinstance(item, Block):
#                     self.count_conditionals(m, item.items)
#                 elif isinstance(item, Always):
#                     self.count_conditionals(m, item.statement)             
#                 elif isinstance(item, Initial):
#                     self.count_conditionals(m, item.statement)
#                 elif isinstance(item, Case):
#                     self.count_conditionals(m, item.statement)
#         elif items != None:
#             if isinstance(items, IfStatement):
#                 m.num_paths *= 2
#                 self.count_conditionals(m, items.true_statement)
#                 self.count_conditionals(m, items.false_statement)
#             if isinstance(items, CaseStatement):
#                 for case in items.caselist:
#                     m.num_paths *= 2
#                     self.count_conditionals(m, case.statement)

#     def lhs_signals(self, m: ExecutionManager, items):
#         """Take stock of which signals are written to in which always blocks for COI analysis."""
#         stmts = items
#         if isinstance(items, Block):
#             stmts = items.statements
#             items.cname = "Block"
#         if hasattr(stmts, '__iter__'):
#             for item in stmts:
#                 if isinstance(item, IfStatement) or isinstance(item, CaseStatement):
#                     if isinstance(item, IfStatement):
#                         self.lhs_signals(m, item.true_statement)
#                         self.lhs_signals(m, item.false_statement)
#                     if isinstance(item, CaseStatement):
#                         for case in item.caselist:
#                             self.lhs_signals(m, case.statement)
#                 if isinstance(item, Block):
#                     self.lhs_signals(m, item.items)
#                 elif isinstance(item, Always):
#                     m.curr_always = item
#                     m.always_writes[item] = []
#                     self.lhs_signals(m, item.statement)             
#                 elif isinstance(item, Initial):
#                     self.lhs_signals(m, item.statement)
#                 elif isinstance(item, Case):
#                     self.lhs_signals(m, item.statement)
#                 elif isinstance(item, Assign):
#                     if isinstance(item.left.var, Partselect):
#                         if m.curr_always is not None and item.left.var.var.name not in m.always_writes[m.curr_always]:
#                             m.always_writes[m.curr_always].append(item.left.var.var.name)
#                     elif m.curr_always is not None and item.left.var.name not in m.always_writes[m.curr_always]:
#                         m.always_writes[m.curr_always].append(item.left.var.name)
#                 elif isinstance(item, NonblockingSubstitution):
#                     if isinstance(item.left.var, Partselect):
#                         if m.curr_always is not None and item.left.var.var.name not in m.always_writes[m.curr_always]:
#                             m.always_writes[m.curr_always].append(item.left.var.var.name)
#                     elif m.curr_always is not None and item.left.var.name not in m.always_writes[m.curr_always]:
#                         m.always_writes[m.curr_always].append(item.left.var.name)
#                 elif isinstance(item, BlockingSubstitution):
#                     if isinstance(item.left.var, Partselect):
#                         if m.curr_always is not None and item.left.var.var.name not in m.always_writes[m.curr_always]:
#                             m.always_writes[m.curr_always].append(item.left.var.var.name)
#                     elif m.curr_always is not None and item.left.var.name not in m.always_writes[m.curr_always]:
#                         m.always_writes[m.curr_always].append(item.left.var.name)
#         elif items != None:
#             if isinstance(items, IfStatement):
#                 self.lhs_signals(m, items.true_statement)
#                 self.lhs_signals(m, items.false_statement)
#             if isinstance(items, CaseStatement):
#                 for case in items.caselist:
#                     self.lhs_signals(m, case.statement)
#             elif isinstance(items, Assign):
#                 if m.curr_always is not None and items.left.var.name not in m.always_writes[m.curr_always]:
#                     m.always_writes[m.curr_always].append(items.left.var.name)
#             elif isinstance(items, NonblockingSubstitution):
#                 if m.curr_always is not None and items.left.var.name not in m.always_writes[m.curr_always]:
#                     m.always_writes[m.curr_always].append(items.left.var.name)
#             elif isinstance(items, BlockingSubstitution):
#                 if m.curr_always is not None and items.left.var.name not in m.always_writes[m.curr_always]:
#                     m.always_writes[m.curr_always].append(items.left.var.name)


#     def get_assertions(self, m: ExecutionManager, items):
#         """Traverse the AST and get the assertion violating conditions."""
#         stmts = items
#         if isinstance(items, Block):
#             stmts = items.statements
#             items.cname = "Block"
#         if hasattr(stmts, '__iter__'):
#             for item in stmts:
#                 if isinstance(item, IfStatement) or isinstance(item, CaseStatement):
#                     if isinstance(item, IfStatement):
#                         # starting to check for the assertions
#                         if isinstance(item.true_statement, Block):
#                             if isinstance(item.true_statement.statements[0], SingleStatement):
#                                 if isinstance(item.true_statement.statements[0].statement, SystemCall) and "ASSERTION" in item.true_statement.statements[0].statement.args[0].value:
#                                     m.assertions.append(item.cond)
#                                     print("assertion found")
#                         else:     
#                             return 
#                             #self.get_assertions(m, item.true_statement)
#                             #self.get_assertions(m, item.false_statement)
#                     if isinstance(item, CaseStatement):
#                         for case in item.caselist:
#                             self.get_assertions(m, case.statement)
#                 elif isinstance(item, Block):
#                     self.get_assertions(m, item.items)
#                 elif isinstance(item, Always):
#                     self.get_assertions(m, item.statement)             
#                 elif isinstance(item, Initial):
#                     self.get_assertions(m, item.statement)
#                 elif isinstance(item, Case):
#                     self.get_assertions(m, item.statement)
#         elif items != None:
#             if isinstance(items, IfStatement):
#                 self.get_assertions(m, items.true_statement)
#                 self.get_assertions(m, items.false_statement)
#             if isinstance(items, CaseStatement):
#                 for case in items.caselist:
#                     self.get_assertions(m, case.statement)

#     def map_assertions_signals(self, m: ExecutionManager):
#         """Map the assertions to a list of relevant signals."""
#         signals = []
#         for assertion in m.assertions:
#             if isinstance(assertion.left, Identifier):
#                 signals.append(assertion.left.name)
#         return signals

#     def assertions_always_intersect(self, m: ExecutionManager):
#         """Get the always blocks that have the signals relevant to the assertions."""
#         signals_of_interest = self.map_assertions_signals(m)
#         blocks_of_interest = []
#         for block in m.always_writes:
#             for signal in signals_of_interest:
#                 if signal in m.always_writes[block]:
#                     blocks_of_interest.append(block)
#         m.blocks_of_interest = blocks_of_interest


#     def seen_all_cases(self, m: ExecutionManager, bit_index: int, nested_ifs: int) -> bool:
#         """Checks if we've seen all the cases for this index in the bit string.
#         We know there are no more nested conditionals within the block, just want to check 
#         that we have seen the path where this bit was turned on but the thing to the left of it
#         could vary."""
#         # first check if things less than me have been added.
#         # so index 29 shouldnt be completed before 30
#         for i in range(bit_index + 1, 32):
#             if not i in m.completed:
#                 return False
#         count = 0
#         seen = m.seen
#         #print(seen)
#         for path in seen[m.curr_module]:
#             if path[bit_index] == '1':
#                 count += 1
#         if count >  2 * nested_ifs:
#             return True
#         return False

#     def module_count(self, m: ExecutionManager, items) -> None:
#         """Traverse a top level module and count up the instances of each type of module."""
#         if isinstance(items, Block):
#             items = items.statements
#         if hasattr(items, '__iter__'):
#             for item in items:
#                 if isinstance(item, InstanceList):
#                     if item.module in m.instance_count:
#                         m.instance_count[item.module] += 1
#                     else:
#                         m.instance_count[item.module] = 1
#                     self.module_count(m, item.instances)
#                 if isinstance(item, Block):
#                     self.module_count(m, item.items)
#                 elif isinstance(item, Always):
#                     self.module_count(m, item.statement)             
#                 elif isinstance(item, Initial):
#                     self.module_count(m, item.statement)
#         elif items != None:
#                 if isinstance(items, InstanceList):
#                     if items.module in m.instance_count:
#                         m.instance_count[items.module] += 1
#                     else:
#                         m.instance_count[items.module] = 1
#                     self.module_count(m, items.instances)


#     def init_run(self, m: ExecutionManager, module: ModuleDef) -> None:
#         """Initalize run."""
#         m.init_run = True
#         self.count_conditionals(m, module.items)
#         self.lhs_signals(m, module.items)
#         self.get_assertions(m, module.items)
#         m.init_run = False
#         #self.module_count(m, module.items)

#     def visit_expr(self, m: ExecutionManager, s: SymbolicState, expr: Value) -> None:
#         if isinstance(expr, Reg):
#             s.store[m.curr_module][expr.name] =''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(16))
#         elif isinstance(expr, Wire):
#             s.store[m.curr_module][expr.name] = init_symbol()
#         elif isinstance(expr, Eq):
#             # assume left is identifier
#             x = BitVec(s.store[m.curr_module][expr.left.name], 32)
            
#             if isinstance(expr.right, IntConst):
#                 y = BitVec(expr.right.value, 32)
#             else:
#                 y = BitVec(expr.right.name, 32)
#             if self.branch:
#                 s.pc.push()
#                 s.pc.add(x==y)
#                 if not self.solve_pc(s.pc):
#                     s.pc.pop()
#                     #print("Abandoning infeasible path")
#                     m.abandon = True
#                     m.ignore  = True
#                     return
#                     print("BAD!")
#             else: 
#                 s.pc.push()
#                 s.pc.add(x != y)
#                 if not self.solve_pc(s.pc):
#                     s.pc.pop()
#                     #print("Abandoning infeasible path")
#                     m.abandon = True
#                     m.ignore = True
#                     return
#                     print("BAD2")
               
#         elif isinstance(expr, Identifier):
#             # change this to one since inst is supposed to just be 1 bit width
#             # and the identifier class actually doesn't have a width param
#             x = BitVec(s.store[m.curr_module][expr.name], 1)
#             y = BitVec(1, 1)
#             if self.branch:
#                 s.pc.push()
#                 s.pc.add(x==y)
#                 if not self.solve_pc(s.pc):
#                     s.pc.pop()
#                     #print("Abandoning infeasible path")
#                     m.abandon = True
#                     m.ignore = True
#                     return
#                     print("BAD!!")
#             else: 
#                 s.pc.push()
#                 s.pc.add(x != y)
#                 if not self.solve_pc(s.pc):
#                     s.pc.pop()
#                     #print("Abandoning infeasible path")
#                     m.abandon = True
#                     m.ignore = True
#                     return
#                     print("BAD2!")


#         # Handling Assertions
#         elif isinstance(expr, NotEql):
#             parse_expr_to_Z3(expr, s.pc, self.branch)
#             # x = BitVec(expr.left.name, 32)
#             # y = BitVec(int(expr.right.value), 32)
#             # if self.branch:
#             #     s.pc.add(x != y)
#             # else: 
#             #     s.pc.add(x == y)
#         elif isinstance(expr, Land):
#             parse_expr_to_Z3(expr, s.pc, self.branch)
#         return None

#     def visit_stmt(self, m: ExecutionManager, s: SymbolicState, stmt: Node, modules: Optional):
#         #print(type(stmt))
#         if isinstance(stmt, Decl):
#             for item in stmt.list:
#                 if isinstance(item, Value):
#                     self.visit_expr(m, s, item)
#                 else:
#                     self.visit_stmt(m, s, item, modules)
#                 # ref_name = item.name
#                 # ref_width = int(item.width.msb.value) + 1
#                 #  dont want to actually call z3 here, just when looking at PC
#                 # x = BitVec(ref_name, ref_width)
#         elif isinstance(stmt, Parameter):
#             if isinstance(stmt.value.var, IntConst):
#                 s.store[m.curr_module][stmt.name] = stmt.value.var
#             elif isinstance(stmt.value.var, Identifier):
#                 s.store[m.curr_module][stmt.name] = s.store[m.curr_module][stmt.value.var]
#             else:
#                 s.store[m.curr_module][stmt.name] = init_symbol()
#         elif isinstance(stmt, Always):
#             sens_list = stmt.sens_list
#             if m.opt_3:
#                 if stmt in m.blocks_of_interest:
#                     sub_stmt = stmt.statement
#                     m.in_always = True
#                     self.visit_stmt(m, s, sub_stmt, modules)
#                     for signal in m.dependencies:
#                         if m.dependencies[m.curr_module][signal] in m.updates:
#                             if m.updates[m.dependencies[m.curr_module][signal]][0] == 1:
#                                 prev_symbol = m.updates[m.dependencies[m.curr_module][signal]][1]
#                                 new_symbol = s.store[m.curr_module][m.dependencies[m.curr_module][signal]]
#                                 s.store[m.curr_module][signal] = s.store[m.curr_module][signal].replace(prev_symbol, new_symbol)
#             else: 
#                 # print(sens_list.list[0].sig) # clock
#                 # print(sens_list.list[0].type) # posedge
#                 sub_stmt = stmt.statement
#                 m.in_always = True
#                 self.visit_stmt(m, s, sub_stmt, modules)
#                 for module in m.dependencies:
#                     for signal in m.dependencies[module]:
#                         if m.dependencies[module][signal] in m.updates:
#                             if m.updates[m.dependencies[module][signal]][0] == 1:
#                                 prev_symbol = m.updates[m.dependencies[module][signal]][1]
#                                 new_symbol = s.store[module][m.dependencies[module][signal]]
#                                 s.store[module][signal] = s.store[module][signal].replace(prev_symbol, new_symbol)
#         elif isinstance(stmt, Assign):
#             if isinstance(stmt.right.var, IntConst):
#                 s.store[m.curr_module][stmt.left.var.name] = stmt.right.var.value
#             elif isinstance(stmt.right.var, Identifier):
#                 s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
#             elif isinstance(stmt.right.var, Partselect):
#                 if isinstance(stmt.left.var, Partselect):
#                     s.store[m.curr_module][stmt.left.var.var.name] = f"{s.store[m.curr_module][stmt.right.var.var.name]}[{stmt.right.var.msb}:{stmt.right.var.lsb}]"
#                     m.dependencies[m.curr_module][stmt.left.var.var.name] = stmt.right.var.var.name
#                     m.updates[stmt.left.var.var.name] = 0
#                 else:
#                     s.store[m.curr_module][stmt.left.var.name] = f"{s.store[m.curr_module][stmt.right.var.var.name]}[{stmt.right.var.msb}:{stmt.right.var.lsb}]"
#                     m.dependencies[m.curr_module][stmt.left.var.name] = stmt.right.var.var.name
#                     m.updates[stmt.left.var.name] = 0
            
#             elif isinstance(stmt.right.var, Concat):
#                 s.store[m.curr_module][stmt.left.var.name] = {}
#                 for item in stmt.right.var.list:
#                     s.store[m.curr_module][stmt.left.var.name][item.name] = s.store[m.curr_module][item.name]
#             else:
#                 new_r_value = evaluate(parse_tokens(tokenize(str(stmt.right.var))), s, m)
#                 if new_r_value != None:
#                     s.store[m.curr_module][stmt.left.var.name] = new_r_value
#                 else:
#                     s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
#         elif isinstance(stmt, NonblockingSubstitution):
#             prev_symbol = s.store[m.curr_module][stmt.left.var.name]
#             if isinstance(stmt.right.var, IntConst):
#                 s.store[m.curr_module][stmt.left.var.name] = stmt.right.var.value
#             elif isinstance(stmt.right.var, Identifier):
#                 s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
#             elif isinstance(stmt.right.var, Concat):
#                 s.store[m.curr_module][stmt.left.var.name] = {}
#                 for item in stmt.right.var.list:
#                     s.store[m.curr_module][stmt.left.var.name][item.name] = s.store[m.curr_module][item.name]
#             elif isinstance(stmt.right.var, StringConst):
#                 s.store[m.curr_module][stmt.left.var.name] = stmt.right.var.value
#             else:
#                 new_r_value = evaluate(parse_tokens(tokenize(str(stmt.right.var))), s, m)
#                 if new_r_value != None:
#                     s.store[m.curr_module][stmt.left.var.name] = new_r_value
#                 else:
#                     s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
#             m.updates[stmt.left.var.name] = (1, prev_symbol)
#         elif isinstance(stmt, BlockingSubstitution):
#             prev_symbol = s.store[m.curr_module][stmt.left.var.name]
#             if isinstance(stmt.right.var, IntConst):
#                 s.store[m.curr_module][stmt.left.var.name] = stmt.right.var.value
#             elif isinstance(stmt.right.var, Identifier):
#                 s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
#             elif isinstance(stmt.right.var, Concat):
#                 s.store[m.curr_module][stmt.left.var.name] = {}
#                 for item in stmt.right.var.list:
#                     if isinstance(item, Partselect):
#                         s.store[m.curr_module][stmt.left.var.name][item.var.name] = f"{s.store[m.curr_module][item.var.name]}[{item.msb}:{item.lsb}]"
#                     else:
#                         s.store[m.curr_module][stmt.left.var.name][item.name] = s.store[m.curr_module][item.name]
#             elif isinstance(stmt.right.var, StringConst):
#                 s.store[m.curr_module][stmt.left.var.name] = stmt.right.var.value
#             else:
#                 new_r_value = evaluate(parse_tokens(tokenize(str(stmt.right.var))), s, m)
#                 if  new_r_value != None:
#                     s.store[m.curr_module][stmt.left.var.name] = new_r_value
#                 else:
#                     s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
#             m.updates[stmt.left.var.name] = (1, prev_symbol)
#         elif isinstance(stmt, Block):
#             for item in stmt.statements: 
#                 self.visit_stmt(m, s, item, modules)
#         elif isinstance(stmt, Initial):
#             self.visit_stmt(m, s, stmt.statement, modules)
#         elif isinstance(stmt, IfStatement):
#             m.curr_level += 1
#             self.cond = True
#             bit_index = len(m.path_code) - m.curr_level
#             if (m.path_code[len(m.path_code) - m.curr_level] == '1'):
#                 self.branch = True

#                 # check if i am the final thing/no more conditionals after me
#                 # basically, we never want me to be true again after this bc we are wasting time reexploring this

#                 self.visit_expr(m, s, stmt.cond)
#                 if (m.abandon):

#                     #print("Abandoning this path!")
#                     return
#                 nested_ifs = self.count_conditionals_2(m, stmt.true_statement)
#                 diff = 32 - bit_index
#                 # m.curr_level == (32 - bit_index) this is always true
#                 #if nested_ifs == 0 and m.curr_level < 2 and self.seen_all_cases(m, bit_index, nested_ifs):
#                 if self.seen_all_cases(m, bit_index, nested_ifs):
#                      m.completed.append(bit_index)
#                 self.visit_stmt(m, s, stmt.true_statement, modules)
#             else:
#                 self.branch = False
#                 self.visit_expr(m, s, stmt.cond)
#                 if (m.abandon):
#                     #print("Abandoning this path!")

#                     return
#                 self.visit_stmt(m, s, stmt.false_statement, modules)
#         elif isinstance(stmt, SystemCall):
#             m.assertion_violation = True
#         elif isinstance(stmt, SingleStatement):
#             self.visit_stmt(m, s, stmt.statement, modules)
#         elif isinstance(stmt, InstanceList):
#             if stmt.module in modules:
#                 for port in stmt.instances[0].portlist:
#                     if str(port.argname) not in s.store[m.curr_module]:
#                         s.store[m.curr_module][str(port.argname)] = init_symbol()
#                         s.store[stmt.module][str(port.portname)] = s.store[m.curr_module][str(port.argname)]
#                     else:
#                         s.store[stmt.module][str(port.portname)] = s.store[m.curr_module][str(port.argname)]
#                 m.opt_1 = False
#                 if m.opt_1:
#                     if m.seen_mod[stmt.module][m.config[stmt.module]] == {}:
#                         #print("hello")
#                         self.execute_child(modules[stmt.module], s, m)
#                     else:
#                         #TODO: Instead of another self.execute, we can just go and grab that state and bring it over int our own
#                         #print("ho")
#                         self.merge_states(m, s, m.seen_mod[stmt.module][m.config[stmt.module]])
#                         # this loop updates all the signals in the top level module
#                         # so that the param connections seem like cont. assigns
#                         for port in stmt.instances[0].portlist:
#                             s.store[m.curr_module][str(port.argname)] = s.store[stmt.module][str(port.portname)]
#                 else:
#                     #print("hey")
#                     for port in stmt.instances[0].portlist:
#                         s.store[m.curr_module][str(port.argname)] = s.store[stmt.module][str(port.portname)]
#                     self.execute_child(modules[stmt.module], s, m)
#         elif isinstance(stmt, CaseStatement):
#             m.curr_level += 1
#             self.cond = True
#             bit_index = len(m.path_code) - m.curr_level

#             if (m.path_code[len(m.path_code) - m.curr_level] == '1'):
#                 self.branch = True

#                 # check if i am the final thing/no more conditionals after me
#                 # basically, we never want me to be true again after this bc we are wasting time reexploring this

#                 self.visit_expr(m, s, stmt.comp)
#                 if (m.abandon):
 
#                     #print("Abandoning this path!")
#                     return
#                 # m.curr_level == (32 - bit_index) this is always true
#                 #if nested_ifs == 0 and m.curr_level < 2 and self.seen_all_cases(m, bit_index, nested_ifs):
#                 self.visit_stmt(m, s, stmt.caselist, modules)
#             else:
#                 self.branch = False
#                 self.visit_expr(m, s, stmt.comp)
#                 if (m.abandon):
#                     #print("Abandoning this path!")

#                     return
#                 self.visit_stmt(m, s, stmt.caselist, modules)

#     def visit_module(self, m: ExecutionManager, s: SymbolicState, module: ModuleDef, modules: Optional):
#         """Visit module."""
#         m.currLevel = 0
#         params = module.paramlist.params
#         ports = module.portlist.ports

#         for param in params:
#             if isinstance(param.list[0], Parameter):
#                 if param.list[0].name not in s.store[m.curr_module]:
#                     s.store[m.curr_module][param.list[0].name] = init_symbol()

#         for port in ports:
#             if isinstance(port, Ioport):
#                 if str(port.first.name) not in s.store[m.curr_module]:
#                     s.store[m.curr_module][str(port.first.name)] = init_symbol()
#             else:
#                 if port.name not in s.store[m.curr_module]:
#                     s.store[m.curr_module][port.name] = init_symbol()

#         if not m.is_child and not m.init_run and not m.ignore:
#             # print("Inital state:")
#             # print(s.store)
#             ...

#         for item in module.items:
#             if isinstance(item, Value):
#                 self.visit_expr(m, s, item)
#             else:
#                 self.visit_stmt(m, s, item, modules)

#         if m.ignore:
#             # print("infeasible path...")
#             ...
        
#         if not m.is_child and not m.init_run and not m.ignore:
#         #if not m.is_child and m.assertion_violation:
#             # print("Final state:")
#             #print(s.store)
       
#             # print("Final path condition:")
#             # print(s.pc)
#             ...
#         elif m.ignore:
#             #print("Path abandoned")
#             m.abandon = False
#             m.ignore = False
#             return
          

#     def populate_child_paths(self, manager: ExecutionManager) -> None:
#         """Populates child path codes based on number of paths."""
#         for child in manager.child_num_paths:
#             manager.child_path_codes[child] = []
#             if manager.piece_wise:
#                 manager.child_path_codes[child] = []
#                 for i in manager.child_range:
#                     manager.child_path_codes[child].append(to_binary(i))
#             else:
#                 for i in range(manager.child_num_paths[child]):
#                     manager.child_path_codes[child].append(to_binary(i))

#     def populate_seen_mod(self, manager: ExecutionManager) -> None:
#         """Populates child path codes but in a format to keep track of corresponding states that we've seen."""
#         for child in manager.child_num_paths:
#             manager.seen_mod[child] = {}
#             for i in range(manager.child_num_paths[child]):
#                 manager.seen_mod[child][(to_binary(i))] = {}

#     def merge_states(self, manager: ExecutionManager, state: SymbolicState, store):
#         """Merges two states."""
#         for key, val in state.store.items():
#             if type(val) != dict:
#                 continue
#             else:
#                 for key2, var in val.items():
#                     if var in store.values():
#                         prev_symbol = state.store[key][key2]
#                         new_symbol = store[key][key2]
#                         state.store[key][key2].replace(prev_symbol, new_symbol)
#                     else:
#                         state.store[key][key2] = store[key][key2]

#     def piece_wise_execute(self, ast: ModuleDef, manager: Optional[ExecutionManager], modules) -> None:
#         """Drives symbolic execution piecewise when number of paths is too large not to breakup. 
#         We break it up to avoid the memory blow up."""

#         self.module_depth += 1
#         manager.piece_wise = True
#         state: SymbolicState = SymbolicState()
#         if manager is None:
#             manager: ExecutionManager = ExecutionManager()
#             manager.debugging = False
#         modules_dict = {}
#         for module in modules:
#             modules_dict[module.name] = module
#             manager.child_path_codes[module.name] = to_binary(0)
#             manager.seen_mod[module.name] = {}
#             sub_manager = ExecutionManager()
#             manager.names_list.append(module.name)
#             self.init_run(sub_manager, module)
#             self.module_count(manager, module.items)
#             manager.child_num_paths[module.name] = sub_manager.num_paths
#             manager.config[module.name] = to_binary(0)
#             state.store[module.name] = {}

#         total_paths = sum(manager.child_num_paths.values())
#         print(total_paths)
#         manager.piece_wise = True
#         #TODO: things piecewise, say 10,000 at a time.
#         for i in range(0, total_paths, 10000):
#             manager.child_range = range(i*10000, i*10000+10000)
#             self.populate_child_paths(manager)
#             if len(modules) > 1:
#                 self.populate_seen_mod(manager)
#                 manager.opt_1 = True
#             else:
#                 manager.opt_1 = False
#             manager.modules = modules_dict
#             paths = list(product(*manager.child_path_codes.values()))
#             #print(f" Upper bound on num paths {len(paths)}")
#             self.init_run(manager, ast)

#             manager.seen = {}
#             for name in manager.names_list:
#                 manager.seen[name] = []
#             manager.curr_module = manager.names_list[0]

#             for i in range(len(paths)):
#                 for j in range(len(paths[i])):
#                     manager.config[manager.names_list[j]] = paths[i][j]
#                 manager.path_code = manager.config[manager.names_list[0]]
#                 if self.check_dup(manager):
#                 # #if False:
#                     continue
#                 else:
#                     print("------------------------")
#                     #print(f"{ast.name} Path {i}")
#                 self.visit_module(manager, state, ast, modules_dict)
#                 manager.seen[ast.name].append(manager.path_code)
#                 if (manager.assertion_violation):
#                     print("Assertion violation")
#                     manager.assertion_violation = False
#                     self.solve_pc(state.pc)
#                 manager.curr_level = 0
#                 manager.dependencies = {}
#                 state.pc.reset()
#             #manager.path_code = to_binary(0)
#             #print(f" finishing {ast.name}")
#             self.module_depth -= 1
    
#     #@profile     
#     def execute(self, ast: ModuleDef, modules, manager: Optional[ExecutionManager], directives, num_cycles: int) -> None:
#         """Drives symbolic execution."""
#         gc.collect()
#         print(f"Executing for {num_cycles} clock cycles")
#         self.module_depth += 1
#         state: SymbolicState = SymbolicState()
#         if manager is None:
#             manager: ExecutionManager = ExecutionManager()
#             manager.debugging = False
#             modules_dict = {}
#             for module in modules:
#                 modules_dict[module.name] = module
#                 manager.child_path_codes[module.name] = to_binary(0)
#                 manager.seen_mod[module.name] = {}
#                 sub_manager = ExecutionManager()
#                 manager.names_list.append(module.name)
#                 self.init_run(sub_manager, module)
#                 self.module_count(manager, module.items)
#                 manager.child_num_paths[module.name] = sub_manager.num_paths
#                 manager.config[module.name] = to_binary(0)
#                 state.store[module.name] = {}
            
#                 manager.dependencies[module.name] = {}

#             total_paths = 1
#             for x in manager.child_num_paths.values():
#                 total_paths *= x
#             #print(total_paths)
#             # have do do things piece wise
#             if total_paths > 100000:
#                 self.piece_wise_execute(ast, manager, modules)
#                 sys.exit()
#             self.populate_child_paths(manager)
#             if len(modules) > 1:
#                 self.populate_seen_mod(manager)
#                 #manager.opt_1 = True
#             else:
#                 manager.opt_1 = False
#             manager.modules = modules_dict
#             paths = list(product(*manager.child_path_codes.values()))
#             #print(f" Upper bound on num paths {len(paths)}")
#         # print(manager.instance_count)
#         # print(manager.always_writes)
#         # print(manager.assertions)

    
#         self.assertions_always_intersect(manager)
#         #print(manager.blocks_of_interest)
#         #print(f"Num paths: {manager.num_paths}")
#         #print(f"Upper bound on num paths {manager.num_paths}")
#         manager.seen = {}
#         for name in manager.names_list:
#             manager.seen[name] = []
#         manager.curr_module = manager.names_list[0]

#         for i in range(len(paths)):
#             for j in range(len(paths[i])):
#                 manager.config[manager.names_list[j]] = paths[i][j]
#             manager.path_code = manager.config[manager.names_list[0]]

#             for cycle in range(int(num_cycles)):
#                 #print(cycle)
#                 if self.check_dup(manager):
#                 #if False:
#                     print("------------------------")
#                     #continue
#                 else:
#                     print("------------------------")
#                     #print(f"{ast.name} Path {i}")
                
#                 self.search_strategy.visit_module(manager, state, ast, modules_dict)
#                 manager.seen[ast.name].append(manager.path_code)
#                 if (manager.assertion_violation):
#                     print("Assertion violation")
#                     manager.assertion_violation = False
#                     self.solve_pc(state.pc)
#                 manager.curr_level = 0
#                 for module in manager.dependencies:
#                     module = {}
#                 state.pc.reset()
#             for name in manager.names_list:
#                 state.store[name] = {}

#             # for module_store in state.store:
#             #     for signal in module_store:
#             #         if signal != "CLK" or signal != "RST":
#             #             print("hi")
#             #             state.store[module_store][signal] = init_symbol()
#         #manager.path_code = to_binary(0)
#         #print(f" finishing {ast.name}")
#         self.module_depth -= 1
#         ## print(state.store)


#     def execute_child(self, ast: ModuleDef, state: SymbolicState, manager: Optional[ExecutionManager]) -> None:
#         """Drives symbolic execution of child modules."""
#         # different manager
#         # same state
#         # dont call pc solve
#         manager_sub = ExecutionManager()
#         manager_sub.is_child = True
#         manager_sub.curr_module = ast.name
#         self.init_run(manager_sub, ast)
#         #print(f"Num paths: {manager.num_paths}")
#         #print(f"Num paths {manager_sub.num_paths}")
#         manager_sub.path_code = manager.config[ast.name]
#         manager_sub.seen = manager.seen

#         # mark this exploration of the submodule as seen and store the state so we don't have to explore it again.
#         if manager.seen_mod[ast.name][manager_sub.path_code] == {}:
#             manager.seen_mod[ast.name][manager_sub.path_code] = state.store
#         else:
#             ...
#             #print("already seen this")
#         # i'm pretty sure we only ever want to do 1 loop here
#         for i in range(1):
#         #for i in range(manager_sub.num_paths):
#             manager_sub.path_code = manager.config[ast.name]
#             #print("------------------------")
#             #print(f"{ast.name} Path {i}")
#             self.visit_module(manager_sub, state, ast, manager.modules)
#             if (manager.assertion_violation):
#                 print("Assertion violation")
#                 manager.assertion_violation = False
#                 self.solve_pc(state.pc)
#             manager.curr_level = 0
#             #state.pc.reset()
#         #manager.path_code = to_binary(0)
#         #print(f" finishing {ast.name}")
#         if manager_sub.ignore:
#             manager.ignore = True
#         self.module_depth -= 1
#         #manager.is_child = False
#         ## print(state.store)
    

def showVersion():
    print(INFO)
    print(VERSION)
    print(USAGE)
    sys.exit()
    
def main():
    """Entrypoint of the program."""
    engine: ExecutionEngine = ExecutionEngine()
    search_strategy: DepthFirst = DepthFirst()
    optparser = OptionParser()
    optparser.add_option("-v", "--version", action="store_true", dest="showversion",
                         default=False, help="Show the version")
    optparser.add_option("-I", "--include", dest="include", action="append",
                         default=["or1200/", "darkriscv/"], help="Include path")
    optparser.add_option("-D", dest="define", action="append",
                         default=[], help="Macro Definition")
    (options, args) = optparser.parse_args()


    num_cycles = args[0]
    filelist = args[1:]

    if options.showversion:
        showVersion()

    for f in filelist:
        if not os.path.exists(f):
            raise IOError("file not found: " + f)

    if len(filelist) == 0:
        showVersion()

    text = preprocess(filelist, include=options.include, define=options.define)
    #print(text)
    ast, directives = parse(filelist,
                            preprocess_include=options.include,
                            preprocess_define=options.define)

    #ast.show()
    print(ast.children()[0].definitions)

    description: Description = ast.children()[0]
    top_level_module: ModuleDef = description.children()[0]
    modules = description.definitions
    start = time.time()
    engine.execute(top_level_module, modules, None, directives, num_cycles)
    end = time.time()
    print(f"Elapsed time {end - start}")

if __name__ == '__main__':
    main()