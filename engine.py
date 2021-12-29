import pyverilog
import z3
from z3 import Solver, Int, BitVec, Context, BitVecSort, ExprRef, BitVecRef, If, BitVecVal
from pyverilog.vparser.parser import parse
from pyverilog.vparser.ast import Description, ModuleDef, Node, IfStatement, SingleStatement, And, Constant, Rvalue, Plus, Input, Output
from pyverilog.vparser.ast import WhileStatement, ForStatement, CaseStatement, Block, SystemCall, Land, InstanceList, IntConst, Partselect, Ioport
from pyverilog.vparser.ast import Value, Reg, Initial, Eq, Identifier, Initial,  NonblockingSubstitution, Decl, Always, Assign, NotEql, Case
import sys
import os
from optparse import OptionParser
from typing import Optional
import random, string
import time
from itertools import product
import logging

with open('errors.log', 'w'):
    pass
logging.basicConfig(filename='errors.log', level=logging.DEBUG)


INFO = "Verilog Symbolic Execution Engine"
VERSION = pyverilog.__version__
USAGE = "Usage: python3 -m engine <verilog_file>.v > out.txt"

CONDITIONALS = (IfStatement, ForStatement, WhileStatement, CaseStatement)
EXPRESSIONS = ["Decl"]

class SymbolicState:
    pc = Solver()
    sort = BitVecSort(32)
    clock_cycle: int = 0
    #TODO need to change to be a nested mapping of module names to dictionaries
    # can be initalized at the beginning of the run 
    store = {}

    # set to true when evaluating a conditoin so that
    # evaluating the expression knows to add the expr to the
    # PC, set to false after
    cond: bool = False

class ExecutionManager:
    num_paths: int = 1
    curr_level: int = 0
    path_code: str = "0" * 12
    ast_str: str = ""
    debugging: bool = False
    abandon: bool = False
    assertion_violation: bool = False
    in_always: bool = False
    modules = {}
    dependencies = {}
    updates = {}
    seen = []
    final = False
    completed = []
    is_child: bool = False
    # Map of module name to path nums for child module
    child_num_paths = {}    
    # Map of module name to path code for child module
    child_path_codes = {}
    paths = []
    config = {}
    names_list = []
    instance_count = {}
    seen_mod = {}
    opt_1: bool = True
    curr_module: str = ""

def to_binary(i: int, digits: int = 32) -> str:
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
            if isinstance(rhs, z3.z3.BitVecRef) and not isinstance(lhs, BitVecRef):
                c = If(lhs, BitVecVal(1, 32), BitVecVal(0, 32))
                s.add(c != rhs)
            else:
                s.add(lhs != rhs)
        else:
            # only RHS is bitVEC 
            if isinstance(rhs, z3.z3.BitVecRef) and not isinstance(lhs, BitVecRef):
                c = If(lhs, BitVecVal(1, 32), BitVecVal(0, 32))
                s.add(c == rhs)
            else:
                s.add(lhs == rhs)
    elif isinstance(e, Land):
        lhs = parse_expr_to_Z3(e.left, s, branch)
        rhs = parse_expr_to_Z3(e.right, s, branch)
        return s.add(lhs.assertions() and rhs.assertions())
    return s


def parse_rvalue(rvalue: Rvalue, store, m: ExecutionManager) -> (str, str, str): 
    #print(rvalue)
    tokens = str(rvalue).replace('(','').replace(')','').split()
    #print(tokens)
    op = ""
    if 'Plus' in tokens[0]:
        op = "+"
    elif 'Minus' in tokens[0]:
        op = '-'
    lhs = tokens[1]
    rhs = tokens[2]
    if not lhs.isdigit():
        if lhs == "Plus":
            try:
                lhs = tokens[2]
                rhs = tokens[3]
            except KeyError:
                logging.debug("hi")
        try:
            lhs = store[m.curr_module][lhs]
        except KeyError:
            logging.debug("hi")
    if not rhs.isdigit():
        # print(store)
        # print(rvalue)
        try: 
            rhs = store[m.curr_module][rhs]
        except KeyError:
            logging.debug('hi2')
    return (lhs, op, rhs)


def init_symbol() -> str:
    """Initializes signal with random symbol."""
    #TODO:change symbol length back to 16 or whatever or make this hash to guarantee good randomness
    return ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(16))
    
     
class ExecutionEngine:
    branch: bool = True
    module_depth: int = 0

    def check_pc_SAT(self, s: Solver, constraint: ExprRef) -> bool:
        """Check if pc is satisfiable before taking path."""
        # the push adds a backtracking point if unsat
        s.push()
        s.add(constraint)
        result = s.check()
        if str(result) == "sat":
            return True
        else:
            s.pop()
            return False

    def check_dup(self, m: ExecutionManager) -> bool:
        """Checks if the current path is a duplicate/worth exploring."""
        for i in range(len(m.path_code)):
            if m.path_code[i] == "1" and i in m.completed:
                return True
        return False

    def solve_pc(self, s: Solver) -> None:
        """Solve path condition."""
        result = str(s.check())
        if str(result) == "sat":
            model = s.model()
            print(model)
        else:
            print("UNSAT/FAILED")

    def count_conditionals_2(self, m:ExecutionManager, items) -> int:
        """Rewrite to actually return an int."""
        stmts = items
        if isinstance(items, Block):
            stmts = items.statements
            items.cname = "Block"

        if hasattr(stmts, '__iter__'):
            for item in stmts:
                if isinstance(item, CONDITIONALS):
                    if isinstance(item, IfStatement) or isinstance(item, CaseStatement):
                        if isinstance(item, IfStatement):
                            return self.count_conditionals_2(m, item.true_statement) + self.count_conditionals_2(m, item.false_statement)  + 1
                        if isinstance(items, CaseStatement):
                            return self.count_conditionals_2(m, items.caselist) + 1
                if isinstance(item, Block):
                    return self.count_conditionals_2(m, item.items)
                elif isinstance(item, Always):
                   return self.count_conditionals_2(m, item.statement)             
                elif isinstance(item, Initial):
                    return self.count_conditionals_2(m, item.statement)
        elif items != None:
            if isinstance(items, IfStatement):
                return  ( self.count_conditionals_2(m, items.true_statement) + 
                self.count_conditionals_2(m, items.false_statement)) + 1
            if isinstance(items, CaseStatement):
                return self.count_conditionals_2(m, items.caselist) + 1
        return 0

    def count_conditionals(self, m: ExecutionManager, items):
        """Identify control flow structures to count total number of paths."""
        stmts = items
        if isinstance(items, Block):
            stmts = items.statements
            items.cname = "Block"
        if hasattr(stmts, '__iter__'):
            for item in stmts:
                if isinstance(item, CONDITIONALS):
                    if isinstance(item, IfStatement) or isinstance(item, CaseStatement):
                        if isinstance(item, IfStatement):
                            m.num_paths *= 2
                            self.count_conditionals(m, item.true_statement)
                            self.count_conditionals(m, item.false_statement)
                        if isinstance(item, CaseStatement):
                            for case in item.caselist:
                                m.num_paths *= 2
                                self.count_conditionals(m, case.statement)
                if isinstance(item, Block):
                    self.count_conditionals(m, item.items)
                elif isinstance(item, Always):
                    self.count_conditionals(m, item.statement)             
                elif isinstance(item, Initial):
                    self.count_conditionals(m, item.statement)
                elif isinstance(item, Case):
                    self.count_conditionals(m, item.statement)
        elif items != None:
            if isinstance(items, IfStatement):
                m.num_paths *= 2
                self.count_conditionals(m, items.true_statement)
                self.count_conditionals(m, items.false_statement)
            if isinstance(items, CaseStatement):
                for case in item.caselist:
                    m.num_paths *= 2
                    self.count_conditionals(m, case.statement)


    def seen_all_cases(self, m: ExecutionManager, bit_index: int, nested_ifs: int) -> bool:
        """Checks if we've seen all the cases for this index in the bit string.
        We know there are no more nested conditionals within the block, just want to check 
        that we have seen the path where this bit was turned on but the thing to the left of it
        could vary."""
        # first check if things less than me have been added.
        # so index 29 shouldnt be completed before 30
        for i in range(bit_index + 1, 32):
            if not i in m.completed:
                return False
        count = 0
        seen = m.seen
        for path in seen:
            if path[bit_index] == '1':
                count += 1
        if count >= nested_ifs:
            return True
        return False

    def module_count(self, m: ExecutionManager, items) -> None:
        """Traverse a top level module and count up the instances of each type of module."""
        if isinstance(items, Block):
            items = items.statements
        if hasattr(items, '__iter__'):
            for item in items:
                if isinstance(item, InstanceList):
                    if item.module in m.instance_count:
                        m.instance_count[item.module] += 1
                    else:
                        m.instance_count[item.module] = 1
                    self.module_count(m, item.instances)
                if isinstance(item, Block):
                    self.module_count(m, item.items)
                elif isinstance(item, Always):
                    self.module_count(m, item.statement)             
                elif isinstance(item, Initial):
                    self.module_count(m, item.statement)
        elif items != None:
                if isinstance(item, InstanceList):
                    if item.module in m.instance_count:
                        m.instance_count[item.module] += 1
                    else:
                        m.instance_count[item.module] = 1
                    self.module_count(m, item.instances)


    def init_run(self, m: ExecutionManager, module: ModuleDef) -> None:
        """Initalize run."""
        self.count_conditionals(m, module.items)
        #self.module_count(m, module.items)

    def visit_expr(self, m: ExecutionManager, s: SymbolicState, expr: Value) -> None:
        if isinstance(expr, Reg):
            s.store[m.curr_module][expr.name] =''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(16))
        elif isinstance(expr, Eq):
            # assume left is identifier
            x = BitVec(s.store[m.curr_module][expr.left.name], 32)
            # assume right is a value
            y = BitVec(int(expr.right.value), 32)
            if self.branch:
                s.pc.add(x == y)
            else: 
                s.pc.add(x != y)
        elif isinstance(expr, Identifier):
            # change this to one since inst is supposed to just be 1 bit width
            # and the identifier class actually doesn't have a width param
            x = BitVec(s.store[m.curr_module][expr.name], 1)
            y = BitVec(1, 1)
            if self.branch:
                s.pc.add(x == y)
            else: 
                s.pc.add(x != y)


        # Handling Assertions
        elif isinstance(expr, NotEql):
            parse_expr_to_Z3(expr, s.pc, self.branch)
            # x = BitVec(expr.left.name, 32)
            # y = BitVec(int(expr.right.value), 32)
            # if self.branch:
            #     s.pc.add(x != y)
            # else: 
            #     s.pc.add(x == y)
        elif isinstance(expr, Land):
            parse_expr_to_Z3(expr, s.pc, self.branch)
        return None

    def visit_stmt(self, m: ExecutionManager, s: SymbolicState, stmt: Node, modules: Optional):
        if isinstance(stmt, Decl):
            for item in stmt.list:
                if isinstance(item, Value):
                    self.visit_expr(m, s, item)
                else:
                    self.visit_stmt(m, s, item, modules)
                # ref_name = item.name
                # ref_width = int(item.width.msb.value) + 1
                #  dont want to actually call z3 here, just when looking at PC
                # x = BitVec(ref_name, ref_width)
        elif isinstance(stmt, Always):
            sens_list = stmt.sens_list
            # print(sens_list.list[0].sig) # clock
            # print(sens_list.list[0].type) # posedge
            sub_stmt = stmt.statement
            m.in_always = True
            self.visit_stmt(m, s, sub_stmt, modules)
            for signal in m.dependencies:
                if m.dependencies[signal] in m.updates:
                    if m.updates[m.dependencies[signal]][0] == 1:
                        prev_symbol = m.updates[m.dependencies[signal]][1]
                        new_symbol = s.store[m.curr_module][m.dependencies[signal]]
                        s.store[signal] = s.store[m.curr_module][signal].replace(prev_symbol, new_symbol)
        elif isinstance(stmt, Assign):
            if isinstance(stmt.right.var, IntConst):
                s.store[m.curr_module][stmt.left.var.name] = stmt.right.var.value
            elif isinstance(stmt.right.var, Partselect):
                if isinstance(stmt.left.var, Partselect):
                    s.store[m.curr_module][stmt.left.var.var.name] = f"{s.store[m.curr_module][stmt.right.var.var.name]}[{stmt.right.var.msb}:{stmt.right.var.lsb}]"
                    m.dependencies[stmt.left.var.var.name] = stmt.right.var.var.name
                    m.updates[stmt.left.var.var.name] = 0
                else:
                    s.store[m.curr_module][stmt.left.var.name] = f"{s.store[m.curr_module][stmt.right.var.var.name]}[{stmt.right.var.msb}:{stmt.right.var.lsb}]"
                    m.dependencies[stmt.left.var.name] = stmt.right.var.var.name
                    m.updates[stmt.left.var.name] = 0
            else:
                (lhs, op, rhs) = parse_rvalue(stmt.right.var, s.store, m)
                if (lhs, op, rhs) != ("","",""):
                    s.store[m.curr_module][stmt.left.var.name] = lhs + op + rhs
                else:
                    s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
        elif isinstance(stmt, NonblockingSubstitution):
            prev_symbol = s.store[m.curr_module][stmt.left.var.name]
            if isinstance(stmt.right.var, IntConst):
                s.store[m.curr_module][stmt.left.var.name] = stmt.right.var.value
            else:
                (lhs, op, rhs) = parse_rvalue(stmt.right.var, s.store, m)
                if (lhs, op, rhs) != ("","",""):
                    s.store[m.curr_module][stmt.left.var.name] = lhs + op + rhs
                else:
                    s.store[m.curr_module][stmt.left.var.name] = s.store[m.curr_module][stmt.right.var.name]
            m.updates[stmt.left.var.name] = (1, prev_symbol)
        elif isinstance(stmt, Block):
            for item in stmt.statements: 
                self.visit_stmt(m, s, item, modules)
        elif isinstance(stmt, Initial):
            self.visit_stmt(m, s, stmt.statement, modules)
        elif isinstance(stmt, IfStatement):
            # print("forking")
            # print(stmt.__dict__)
            m.curr_level += 1
            self.cond = True
            bit_index = len(m.path_code) - m.curr_level

            if (m.path_code[len(m.path_code) - m.curr_level] == '1'):
                self.branch = True

                # check if i am the final thing/no more conditionals after me
                # basically, we never want me to be true again after this bc we are wasting time reexploring this

                self.visit_expr(m, s, stmt.cond)
                if (m.abandon):
                    m.abandon = False
                    print("Abandoning this path!")
                    return
                nested_ifs = self.count_conditionals_2(m, stmt.true_statement)
                diff = 32 - bit_index
                # m.curr_level == (32 - bit_index) this is always true
                #if nested_ifs == 0 and m.curr_level < 2 and self.seen_all_cases(m, bit_index, nested_ifs):
                if self.seen_all_cases(m, bit_index, nested_ifs):
                     m.completed.append(bit_index)
                self.visit_stmt(m, s, stmt.true_statement, modules)
            else:
                self.branch = False
                self.visit_expr(m, s, stmt.cond)
                if (m.abandon):
                    print("Abandoning this path!")
                    m.abandon = False
                    return
                self.visit_stmt(m, s, stmt.false_statement, modules)
        elif isinstance(stmt, SystemCall):
            m.assertion_violation = True
        elif isinstance(stmt, SingleStatement):
            self.visit_stmt(m, s, stmt.statement, modules)
        elif isinstance(stmt, InstanceList):
            if stmt.module in modules:
                if m.opt_1:
                    if m.seen_mod[stmt.module][m.config[stmt.module]] == {}:
                        print("Not seen")
                        self.execute_child(modules[stmt.module], s, m)
                    else:
                        print("seen")
                        #TODO: Instead of another self.execute, we can just go and grab that state and bring it over int our own
                        self.merge_states(m, s, m.seen_mod[stmt.module][m.config[stmt.module]])
                else:
                    self.execute_child(modules[stmt.module], s, m)
        elif isinstance(stmt, CaseStatement):
            m.curr_level += 1
            self.cond = True
            bit_index = len(m.path_code) - m.curr_level

            if (m.path_code[len(m.path_code) - m.curr_level] == '1'):
                self.branch = True

                # check if i am the final thing/no more conditionals after me
                # basically, we never want me to be true again after this bc we are wasting time reexploring this

                self.visit_expr(m, s, stmt.comp)
                if (m.abandon):
                    m.abandon = False
                    print("Abandoning this path!")
                    return
                # m.curr_level == (32 - bit_index) this is always true
                #if nested_ifs == 0 and m.curr_level < 2 and self.seen_all_cases(m, bit_index, nested_ifs):
                self.visit_stmt(m, s, stmt.caselist, modules)
            else:
                self.branch = False
                self.visit_expr(m, s, stmt.comp)
                if (m.abandon):
                    print("Abandoning this path!")
                    m.abandon = False
                    return
                self.visit_stmt(m, s, stmt.caselist, modules)

    def visit_module(self, m: ExecutionManager, s: SymbolicState, module: ModuleDef, modules: Optional):
        """Visit module."""
        m.currLevel = 0
        #print(m.path_code)
        params = module.paramlist.params
        ports = module.portlist.ports


        for port in ports:
            if isinstance(port, Ioport):
                s.store[m.curr_module][port.first.name] = init_symbol()
            else:
                s.store[m.curr_module][port.name] = init_symbol()

        for item in module.items:
            if isinstance(item, Value):
                self.visit_expr(m, s, item)
            else:
                self.visit_stmt(m, s, item, modules)
        
        if not m.is_child:
            print("Final state:")
            print(s.store)
            print("Final path condition:")
            print(s.pc)
          

    def populate_child_paths(self, manager: ExecutionManager) -> None:
        """Populates child path codes based on number of paths."""
        for child in manager.child_num_paths:
            manager.child_path_codes[child] = []
            for i in range(manager.child_num_paths[child]):
                manager.child_path_codes[child].append(to_binary(i))

    def populate_seen_mod(self, manager: ExecutionManager) -> None:
        """Populates child path codes but in a format to keep track of corresponding states that we've seen."""
        for child in manager.child_num_paths:
            manager.seen_mod[child] = {}
            for i in range(manager.child_num_paths[child]):
                manager.seen_mod[child][(to_binary(i))] = {}

    def merge_states(self, manager: ExecutionManager, state: SymbolicState, store):
        """Merges two states."""
        print(state.store)
        for key, val in state.store.items():
            if type(val) != dict:
                continue
            else:
                for key2, var in val.items():
                    if var in store.values():
                        prev_symbol = state.store[key][key2]
                        new_symbol = store[key][key2]
                        state.store[key][key2].replace(prev_symbol, new_symbol)
                    else:
                        state.store[key][key2] = store[key][key2]
            
    def execute(self, ast: ModuleDef, modules, manager: Optional[ExecutionManager]) -> None:
        """Drives symbolic execution."""
        self.module_depth += 1
        state: SymbolicState = SymbolicState()
        if manager is None:
            manager: ExecutionManager = ExecutionManager()
            manager.debugging = False
            modules_dict = {}
            for module in modules:
                modules_dict[module.name] = module
                manager.child_path_codes[module.name] = to_binary(0)
                manager.seen_mod[module.name] = {}
                sub_manager = ExecutionManager()
                manager.names_list.append(module.name)
                self.init_run(sub_manager, module)
                self.module_count(manager, module.items)
                manager.child_num_paths[module.name] = sub_manager.num_paths
                manager.config[module.name] = to_binary(0)
                state.store[module.name] = {}
            self.populate_child_paths(manager)
            self.populate_seen_mod(manager)
            manager.modules = modules_dict
            paths = list(product(*manager.child_path_codes.values()))
            print(f" Upper bound on num paths {len(paths)}")
        self.init_run(manager, ast)
        print(manager.instance_count)
        #print(f"Num paths: {manager.num_paths}")
        #print(f"Upper bound on num paths {manager.num_paths}")
        manager.seen = []
        manager.curr_module = module.name
        for i in range(len(paths)):
            for j in range(len(paths[i])):
                manager.config[manager.names_list[j]] = paths[i][j]
            manager.path_code = manager.config[manager.names_list[0]]
            if self.check_dup(manager):
            #if False:
                continue
            else:
                print("------------------------")
                print(f"{ast.name} Path {i}")
            print(paths[i])
            self.visit_module(manager, state, ast, modules_dict)
            manager.seen.append(manager.path_code)
            if (manager.assertion_violation):
                print("Assertion violation")
                manager.assertion_violation = False
                self.solve_pc(state.pc)
            manager.curr_level = 0
            manager.dependencies = {}
            state.pc.reset()
        #manager.path_code = to_binary(0)
        print(f" finishing {ast.name}")
        self.module_depth -= 1
        ## print(state.store)


    def execute_child(self, ast: ModuleDef, state: SymbolicState, manager: Optional[ExecutionManager]) -> None:
        """Drives symbolic execution of child modules."""
        # different manager
        # same state
        # dont call pc solve
        manager_sub = ExecutionManager()
        manager_sub.is_child = True
        manager_sub.curr_module = ast.name
        self.init_run(manager_sub, ast)
        #print(f"Num paths: {manager.num_paths}")
        print(f"Num paths {manager_sub.num_paths}")
        manager_sub.path_code = manager.config[ast.name]

        # mark this exploration of the submodule as seen and store the state so we don't have to explore it again.
        if manager.seen_mod[ast.name][manager_sub.path_code] == {}:
            manager.seen_mod[ast.name][manager_sub.path_code] = state.store
        else:
            print("already seen this")
        # i'm pretty sure we only ever want to do 1 loop here
        for i in range(1):
        #for i in range(manager_sub.num_paths):
            manager_sub.path_code = manager.config[ast.name]
            print("------------------------")
            print(f"{ast.name} Path {i}")
            self.visit_module(manager_sub, state, ast, manager.modules)
            if (manager.assertion_violation):
                print("Assertion violation")
                manager.assertion_violation = False
                self.solve_pc(state.pc)
            manager.curr_level = 0
            #state.pc.reset()
        #manager.path_code = to_binary(0)
        print(f" finishing {ast.name}")
        self.module_depth -= 1
        manager.is_child = False
        ## print(state.store)
    

def showVersion():
    print(INFO)
    print(VERSION)
    print(USAGE)
    sys.exit()
    
def main():
    """Entrypoint of the program."""
    engine: ExecutionEngine = ExecutionEngine()
    optparser = OptionParser()
    optparser.add_option("-v", "--version", action="store_true", dest="showversion",
                         default=False, help="Show the version")
    optparser.add_option("-I", "--include", dest="include", action="append",
                         default=[], help="Include path")
    optparser.add_option("-D", dest="define", action="append",
                         default=[], help="Macro Definition")
    (options, args) = optparser.parse_args()

    filelist = args
    if options.showversion:
        showVersion()

    for f in filelist:
        if not os.path.exists(f):
            raise IOError("file not found: " + f)

    if len(filelist) == 0:
        showVersion()

    ast, directives = parse(filelist,
                            preprocess_include=options.include,
                            preprocess_define=options.define)

    #ast.show()

    description: Description = ast.children()[0]
    top_level_module: ModuleDef = description.children()[0]
    modules = description.definitions
    start = time.time()
    engine.execute(top_level_module, modules, None)
    end = time.time()
    print(f"Elapsed time {end - start}")

if __name__ == '__main__':
    main()