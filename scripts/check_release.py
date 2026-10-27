"""Check a source publication inventory without printing potential secret values."""
from pathlib import Path
import re,sys,json,subprocess
root=Path(__file__).resolve().parents[1]
bad=[];files=[]
patterns=[re.compile(rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}'),re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{24,}'),re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')]
tracked=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,text=True)
targets=[root/p for p in tracked.stdout.split('\0') if p] if tracked.returncode==0 and tracked.stdout else root.rglob('*')
for p in targets:
    if not p.is_file() or '.git' in p.parts:continue
    rel=p.relative_to(root)
    if any(s in rel.parts for s in ['node_modules','.venv','__pycache__','.runtime','logs']) or str(rel).startswith('backend/data/') or p.suffix in {'.db','.sqlite3','.pem','.key'} or (p.name.startswith('.env') and p.name!='.env.example'):
        bad.append({'path':str(rel),'reason':'local state or credential file excluded by policy'});continue
    b=p.read_bytes()
    if any(r.search(b) for r in patterns):bad.append({'path':str(rel),'reason':'possible credential pattern; inspect locally'})
    files.append({'path':str(rel),'bytes':len(b)})
print(json.dumps({'files':len(files),'bytes':sum(x['bytes'] for x in files),'findings':bad},ensure_ascii=False,indent=2))
sys.exit(bool(bad))
