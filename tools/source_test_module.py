"""Execute one original test module with assertions and explicit capture gaps."""
import os,sys,json,socket,time,types,unittest,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=Path(os.environ['SOURCE_TEST_OUT']);name=sys.argv[-1]
assert name.startswith('test_') and '/' not in name and '\\' not in name
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.source_bootstrap import ensure_source_package
ensure_source_package(ROOT)
from qt.core import QApplication,QT_VERSION_STR,PYQT_VERSION_STR
app=QApplication.instance() or QApplication([])
def blocked(*a,**kw):raise AssertionError('Portable source tests cannot use live network')
socket.create_connection=blocked;socket.socket.connect=blocked
class Recorded(unittest.TextTestResult):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.outcomes=[]
    def addSuccess(self,t):super().addSuccess(t);self.outcomes.append(dict(id=t.id(),outcome='pass'))
    def addFailure(self,t,e):super().addFailure(t,e);self.outcomes.append(dict(id=t.id(),outcome='fail',traceback=self.failures[-1][1]))
    def addError(self,t,e):super().addError(t,e);self.outcomes.append(dict(id=t.id(),outcome='error',traceback=self.errors[-1][1]))
    def addSkip(self,t,r):super().addSkip(t,r);self.outcomes.append(dict(id=t.id(),outcome='skip',reason=r))
started=time.monotonic();path=ROOT/'tests'/(name+'.py')
try:
    module=types.ModuleType(name);module.__file__=str(path);module.__package__='';sys.modules[name]=module
    exec(compile(path.read_bytes(),str(path),'exec',optimize=0),module.__dict__)
    policy=json.loads((ROOT/'tests/source_suite_policy.json').read_text(encoding='utf8'))
    for cls in vars(module).values():
        if isinstance(cls,type) and issubclass(cls,unittest.TestCase):
            for method in unittest.defaultTestLoader.getTestCaseNames(cls):
                reason=policy['unavailable_methods'].get(name+'.'+method)
                if reason:setattr(cls,method,unittest.skip(reason)(getattr(cls,method)))
    suite=unittest.defaultTestLoader.loadTestsFromModule(module)
    with (OUT/(name+'.tests.log')).open('w',encoding='utf8') as log:result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Recorded).run(suite)
    record=dict(run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),outcomes=result.outcomes,qt=QT_VERSION_STR,pyqt=PYQT_VERSION_STR,elapsed_s=time.monotonic()-started)
except BaseException:record=dict(run=0,failures=0,errors=1,load_traceback=traceback.format_exc())
(OUT/(name+'.json')).write_text(json.dumps(record,indent=2),encoding='utf8')
if record['failures'] or record['errors']:raise SystemExit(1)
